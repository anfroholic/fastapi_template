
from fastapi import Depends, FastAPI, Request, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse
from pydantic import BaseModel
import os



class User:
    def __init__(self, name, email, admin):
        self.is_authenticated = True
        self.name = name
        self.is_admin = admin
        self.email = email

test_user = User('testy McTestface', 'test@test.com', True)


areas = {
    'lasers': ['boss', 'universal'],
    'cnc': ['shopbot'],
    '3dprinters': ['fdm_3dprinters'],
    'cold_metals': ['cnc_lathe', 'tormach'],
    'hot_metals': ['mig_welder', 'tig_welder', 'forge'],
    'woodshop': ['wood_lathe', 'bandsaw', 'sawstop'],
}    


class Member:
    def __init__(self, name, email, status, joined, authorizations):
        self.name = name
        self.email = email
        self.status = status
        self.joined = joined
        self.authorizations = authorizations
        self.id_checked = True
        
test_member = Member(
    name='testy McTestface',
    email='test@test.com',
    status='active',
    joined='2023-01-01',
    authorizations=[
        'boss',
        'universal',
        'shopbot',
        'fdm_3dprinters',
        'bandsaw', 
        'sawstop',
    ]
)



app = FastAPI()
templates = Jinja2Templates(directory='htmldirectory')
app.mount("/static", StaticFiles(directory="static", html=True), name="static")


@app.get('/', response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse('base.html', {'request': request, 'content': '', "search": 'none', "current_user": test_user, 'active_page': 'home'})

@app.get('/search', name='search', response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse('search.html', {'request': request, "search": 'none', "current_user": test_user})

@app.get('/member', name='member', response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse('member.html', {'request': request, 'content': '', "search": 'none', "current_user": test_user, 'member': test_member, 'active_page': 'member', 'areas': areas})


@app.get('/redirect', response_class=HTMLResponse)
async def redir(request: Request):
    response = RedirectResponse(url='/')
    return response

@app.post('/set_member', response_class=JSONResponse)
async def set_member(request: Request, body: dict = Body(...)):
    print(body)
    return body