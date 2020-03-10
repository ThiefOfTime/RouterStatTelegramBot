# Thief's Arxiv Telegram Bot
This bot manages Arxiv subscriptions and pulls the informations of the newest papers. This information contains the name, arxiv name and depending on the user input the link to the abstract or directly to the pdf file.
## Prerequisites
Make sure your mysql database is up and running and is containing a stats table. For more informations see the dbexport.sql file.
## Requirements
The script was programmed and tested with Python3.7
## Installation
Run `pip install -r requirements.txt`  
Edit the conf file by replacing the placeholders with corresponding values  
After installing the packages simply run `python arxivbot.py`