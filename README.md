# ETHUSD_system

This project uses venv as a virtual environment to isolate dependencies:
```
python -m venv .venv
```
Activate virtual environment before install dependencies:
```
Windows (Command Prompt):
.venv\Scripts\activate

Windows (PowerShell):
.venv\Scripts\Activate.ps1

Mac/Linux:
source .venv/bin/activate
```
If activation fails on Windows PowerShell, run:
```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
Install dependencies by running this in bash
```
pip install .
```
