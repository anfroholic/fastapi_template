"""Open Silicon Component Exchange -- a "Thingiverse for chips" prototype.

Browse and inspect pre-hardened silicon macros. This prototype focuses on
display / UX: a playful catalog of cards, a datasheet-style detail page with a
LEF-parsed footprint and corner-coverage matrix, and file downloads. Users and
publishing are intentionally out of scope for now.
"""
import io
import os
import zipfile

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from catalog import CATALOG, SIGNOFF_CHECKS

app = FastAPI(title="Open Silicon Component Exchange")
templates = Jinja2Templates(directory="htmldirectory")
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

def facet_url(active: dict, key: str, value) -> str:
    """Build a catalog URL that sets one facet to `value` while keeping the rest."""
    params = {k: active.get(k) for k in ("q", "function", "pdk", "node", "license", "sort")}
    params[key] = value
    if active.get("signoff_clean"):
        params["signoff_clean"] = "true"
    query = "&".join(f"{k}={v}" for k, v in params.items() if v)
    return "/?" + query if query else "/"


# Make helpers available to every template.
templates.env.globals["signoff_checks"] = SIGNOFF_CHECKS
templates.env.globals["facet_url"] = facet_url


@app.get("/", response_class=HTMLResponse)
async def catalog(
    request: Request,
    q: str | None = None,
    function: str | None = None,
    pdk: str | None = None,
    node: str | None = None,
    license: str | None = None,
    signoff_clean: bool = False,
    sort: str = "name",
):
    components = CATALOG.filter(
        q=q, function=function, pdk=pdk, node=node, license=license,
        signoff_clean=signoff_clean, sort=sort,
    )
    return templates.TemplateResponse(
        request,
        "catalog.html",
        {
            "components": components,
            "total": len(CATALOG.components),
            "facets": CATALOG.facets(),
            "active": {
                "q": q or "", "function": function, "pdk": pdk, "node": node,
                "license": license, "signoff_clean": signoff_clean, "sort": sort,
            },
        },
    )


@app.get("/component/{name}", response_class=HTMLResponse)
async def component_detail(request: Request, name: str):
    comp = CATALOG.get(name)
    if comp is None:
        return HTMLResponse(_not_found(name), status_code=404)
    return templates.TemplateResponse(request, "detail.html", {"c": comp})


@app.get("/component/{name}/render.png")
async def render_png(name: str):
    """Serve the rendered layout image (the 'GDS view'), if it has been produced."""
    comp = CATALOG.get(name)
    if comp is None or not comp.has_render:
        return HTMLResponse("No render available", status_code=404)
    return FileResponse(comp.render_path, media_type="image/png")


@app.get("/component/{name}/download")
async def download_package(name: str):
    """Zip up the whole package (all 4 view types + metadata) on the fly."""
    comp = CATALOG.get(name)
    if comp is None:
        return HTMLResponse(_not_found(name), status_code=404)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(comp.path):
            for fn in files:
                full = os.path.join(root, fn)
                arc = os.path.join(name, os.path.relpath(full, comp.path))
                zf.write(full, arc)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@app.get("/component/{name}/file/{view:path}")
async def download_file(name: str, view: str):
    """Serve a single view file for inline preview / individual download."""
    comp = CATALOG.get(name)
    if comp is None:
        return HTMLResponse(_not_found(name), status_code=404)
    # Guard against path traversal: resolve and confirm it stays inside the pkg.
    target = os.path.normpath(os.path.join(comp.path, view))
    if not target.startswith(os.path.normpath(comp.path) + os.sep):
        return HTMLResponse("Invalid path", status_code=400)
    if not os.path.isfile(target):
        return HTMLResponse("File not found", status_code=404)
    # Text views (.lef/.vh/.lib) preview inline; binaries (.gds.gz) download.
    media = "text/plain"
    if target.endswith(".gz"):
        media = "application/gzip"
    elif target.endswith(".gds"):
        media = "application/octet-stream"
    return FileResponse(target, filename=os.path.basename(target), media_type=media)


def _not_found(name: str) -> str:
    return f"<h1>404</h1><p>No component named <code>{name}</code>.</p><a href='/'>Back to catalog</a>"
