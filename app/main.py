
from fastapi import Depends, FastAPI, Request, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse
from pydantic import BaseModel
import os
import json

RESULTS_FILE = os.path.join(os.path.dirname(__file__), 'results.json')

def load_results():
    try:
        with open(RESULTS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"votes": []}

def save_results(data):
    with open(RESULTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


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


@app.get('/home', response_class=HTMLResponse)
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


@app.get('/', name='vote', response_class=HTMLResponse)
async def vote_page(request: Request):
    return templates.TemplateResponse('vote.html', {'request': request})


@app.post('/vote', response_class=JSONResponse)
async def submit_vote(request: Request, body: dict = Body(...)):
    name = body.get('name', '').strip()
    rankings = body.get('rankings', [])

    if not name:
        return JSONResponse({'success': False, 'error': 'Name is required'}, status_code=400)
    if not rankings:
        return JSONResponse({'success': False, 'error': 'Rankings are required'}, status_code=400)

    results = load_results()

    # Check for duplicate vote by name
    for vote in results['votes']:
        if vote['name'].lower() == name.lower():
            return JSONResponse({'success': False, 'error': 'You have already voted'}, status_code=400)

    results['votes'].append({'name': name, 'rankings': rankings})
    save_results(results)

    return {'success': True}


@app.get('/results', name='results', response_class=HTMLResponse)
async def results_page(request: Request):
    results = load_results()
    votes = results.get('votes', [])

    # Calculate points: 1st place = N points, 2nd = N-1, etc.
    scores = {}
    for vote in votes:
        rankings = vote.get('rankings', [])
        n = len(rankings)
        for i, item in enumerate(rankings):
            points = n - i
            if item not in scores:
                scores[item] = {'points': 0, 'votes': 0}
            scores[item]['points'] += points
            scores[item]['votes'] += 1

    # Sort by points descending
    leaderboard = sorted(scores.items(), key=lambda x: x[1]['points'], reverse=True)

    return templates.TemplateResponse('results.html', {
        'request': request,
        'leaderboard': leaderboard,
        'total_voters': len(votes)
    })