from fastapi import FastAPI, Request, Form, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
import hmac
import hashlib
import json
import uuid

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

JWT_SECRET = "dev-access-secret"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=10)

REFRESH_SECRET = b"dev-refresh-secret"
REFRESH_TOKEN_TTL = timedelta(days=7)

# Session store (refresh tokens)
refresh_store: dict[str, dict] = {}

# -------------------------------------------------------------------
# Token creation
# -------------------------------------------------------------------

def create_access_token(payload: dict) -> str:
    now = datetime.now(timezone.utc)
    claims = payload.copy()
    claims.update({ 
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
        "iss": "example-app",
    })
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(payload: dict) -> str:
    now = datetime.now(timezone.utc)
    data = payload.copy()
    data.update({
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + REFRESH_TOKEN_TTL).timestamp()),
    })

    raw = json.dumps(data, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(REFRESH_SECRET, raw.encode(), hashlib.sha256).hexdigest()

    refresh_store[data["jti"]] = {
        "sub": data["sub"],
        "roles": data["roles"],
        "issued_at": data["iat"],
        "exp": data["exp"],
        "last_seen": data["iat"],
    }

    print(f"Created refresh token for {data['sub']} with jti {data['jti']}")
    return f"{raw}.{sig}"


def verify_refresh_token(token: str) -> dict | None:
    try:
        raw, sig = token.rsplit(".", 1)
        expected = hmac.new(
            REFRESH_SECRET, raw.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(sig, expected):
            return None

        data = json.loads(raw)

        if datetime.now(timezone.utc).timestamp() > data["exp"]:
            return None

        session = refresh_store.get(data["jti"])
        if not session:
            return None

        session["last_seen"] = int(datetime.now(timezone.utc).timestamp())
        return data

    except Exception:
        return None

# -------------------------------------------------------------------
# Authentication helpers
# -------------------------------------------------------------------

def authenticate_request(request: Request) -> dict | None:
    token = request.cookies.get("access_token")
    if not token:
        return None

    try:
        return jwt.decode( 
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer="example-app",
        )
    except JWTError:
        return None


def attempt_refresh(request: Request, response: Response) -> dict | None:
    token = request.cookies.get("refresh_token")
    if not token:
        return None

    data = verify_refresh_token(token)
    if not data:
        return None

    # Rotate refresh token
    refresh_store.pop(data["jti"], None)

    payload = {"sub": data["sub"], "roles": data["roles"]}
    new_access = create_access_token(payload)
    new_refresh = create_refresh_token(payload)

    response.set_cookie(
        "access_token", new_access,
        httponly=True, secure=True, samesite="lax"
    )
    response.set_cookie(
        "refresh_token", new_refresh,
        httponly=True, secure=True, samesite="lax"
    )

    return payload


def require_admin(user: dict):
    if "admin" not in user.get("roles", []):
        raise HTTPException(status_code=403)

# -------------------------------------------------------------------
# SSR Routes
# -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = authenticate_request(request)
    print(f"User {user['sub']} accessed index") if user else print("Unauthenticated access to index")
    response = templates.TemplateResponse(
        "index.html",
        {"request": request, "user": user}
    )

    if not user:
        refreshed = attempt_refresh(request, response)
        if refreshed:
            response.context["user"] = refreshed

    return response


@app.post("/login")
def login(username: str = Form(...)):
    # Promote a specific user to admin for demo purposes
    roles = ["admin"] if username == "admin" else ["user"]

    payload = {"sub": username, "roles": roles}
    response = RedirectResponse("/", status_code=303)

    response.set_cookie(
        "access_token",
        create_access_token(payload),
        httponly=True, secure=True, samesite="lax",
    )
    response.set_cookie(
        "refresh_token",
        create_refresh_token(payload),
        httponly=True, secure=True, samesite="lax",
    )

    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    user = authenticate_request(request)
    if not user:
        raise HTTPException(status_code=401)

    require_admin(user)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "sessions": refresh_store,
        }
    )

# -------------------------------------------------------------------
# API Routes
# -------------------------------------------------------------------

@app.get("/api/me")
def api_me(request: Request):
    user = authenticate_request(request)
    if not user:
        raise HTTPException(status_code=401)
    return user


@app.get("/api/heartbeat")
def api_heartbeat(request: Request):
    user = authenticate_request(request)
    if not user:
        raise HTTPException(status_code=401)
    return {"authenticated": True}


@app.post("/api/admin/revoke/{jti}")
def revoke_session(jti: str, request: Request):
    user = authenticate_request(request)
    if not user:
        raise HTTPException(status_code=401)

    require_admin(user)

    refresh_store.pop(jti, None)
    return {"revoked": jti}
