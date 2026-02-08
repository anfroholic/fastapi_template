
from fastapi import Depends, FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse
from pydantic import BaseModel
import os

ENV_1 = os.getenv("ENV_1")
ENV_2 = os.getenv("ENV_2")

class FormModel(BaseModel):
    form1: str
    form2: str
    form3: str
    form4: str

app = FastAPI()
templates = Jinja2Templates(directory='htmldirectory')
app.mount("/static", StaticFiles(directory="static", html=True), name="static")


@app.get('/', response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse('index.html', {'request': request, 'env_1': ENV_1, 'env_2': ENV_2})


@app.get('/redirect', response_class=HTMLResponse)
async def redir(request: Request):
    response = RedirectResponse(url='/')
    return response

@app.get('/arg/{arg}', response_class=JSONResponse)
async def arg(arg: str):
    return {"the_arg_is": arg}

@app.post('/query_form', response_class=JSONResponse)
async def q_form(request: Request, form1: str=Form(...), form2: str=Form(...)):
    return {"form1": form1, "form2": form2}

@app.post('/query_raw', response_class=JSONResponse)
async def q_raw(request: Request):
    raw_form = dict(await request.form())
    
    return {"raw_form": raw_form}

@app.get('/query_get', response_class=JSONResponse)
async def q_get(request: Request, form1: str, form2:str):
    return {"form1": form1, 'form2': form2}

@app.post('/form_model', response_class=JSONResponse)
async def f_model(request: Request, form_model: FormModel):
    print(form_model)
    return {"form_model": form_model}
