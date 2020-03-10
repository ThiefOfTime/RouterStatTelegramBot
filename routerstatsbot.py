from os.path import isfile
import pickle
from telegram.ext import Updater, CommandHandler, Filters
from telegram import Bot
from fritzconnection import FritzConnection
from fritzconnection.lib.fritzwlan import FritzWLAN
from fritzconnection.lib.fritzhosts import FritzHosts
from fritzconnection.lib.fritzstatus import FritzStatus
import time
import schedule
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.automap import automap_base
from datetime import datetime


statistics = {'transRateKBUpMax': 0, 'transRateKBDownMax': 0, 'transRateKBUpMin': 0, 'transRateKBDownMin': 0}
host_list = {}
last_message_id = {}
transmission_info_five_minutes = {}
trans_count = 0

with open("conf.backup", "r") as config:
    key = config.readline().split(":", 1)[-1].strip()
    allowed_users = [int(x) for x in config.readline().split(':', 1)[-1].strip().split(',') if len(x) > 0]
    router_ip = config.readline().split(':', 1)[-1].strip()
    router_pw = config.readline().split(':', 1)[-1].strip()
    db_vals = config.readline().split(':', 1)[-1].strip()
    user, user_pw, location, port, database = db_vals.split(',')
    port = int(port)

router_connection = FritzConnection(address=router_ip, password=router_pw)
router_wlan = FritzWLAN(router_connection)
router_host = FritzHosts(router_connection)
router_status = FritzStatus(router_connection)

router_model = router_status.modelname

metadata = MetaData()
db_engine = create_engine(f'mysql+pymysql://{user}:{user_pw}@{location}:{port}/{database}')
metadata.reflect(db_engine, only=['stats'])
Base = automap_base(metadata=metadata)
Base.prepare()
db_statistics_class = Base.classes.stats
Session = sessionmaker(bind=db_engine)
db_session = Session()


# general functions
def write_to_database():
    max_byte_up, max_byte_down = router_status.max_byte_rate
    db_session.add(db_statistics_class(date=datetime.today(), numberOfActiveHosts=sum(host['status'] for host in router_host.get_hosts_info()),
                                       publicIPv4=router_status.external_ip, publicIPv6=router_status.external_ipv6,
                                       linked=router_status.is_linked, connected=router_status.is_connected,
                                       maxByteRateUp=int(max_byte_up), maxByteRateDown=int(max_byte_down),
                                       uptimeInSec=router_status.uptime, transRateKBUpMean=float(f'{(transmission_info_five_minutes["up"] / trans_count):.3f}'),
                                       transRateKBDownMean=float(f'{(transmission_info_five_minutes["down"] / trans_count):.3f}'),
                                       transRateKBUpMax=statistics['transRateKBUpMax'], transRateKBDownMax=statistics['transRateKBDownMax'],
                                       transRateKBUpMin=statistics['transRateKBUpMin'], transRateKBDownMin=statistics['transRateKBDownMin']))
    db_session.commit()


# repeated functions
def gather_transmission_informations(context):
    global transmission_info_five_minutes
    global statistics
    global trans_count
    up, down = router_status.str_transmission_rate
    up, val = up.split()
    if val == 'bytes':
        up = float(up) / 1000
    elif val == 'MB':
        up = float(up) * 1000
    elif val == 'GB':
        up = float(up) * 1000000
    else:
        up = float(up)
    down, val = down.split()
    if val == 'bytes':
        down = float(down) / 1000
    elif val == 'MB':
        down = float(down) * 1000
    elif val == 'GB':
        down = float(down) * 1000000
    else:
        down = float(down)
    if len(transmission_info_five_minutes.keys()) == 0:
        transmission_info_five_minutes["up"] = up
        transmission_info_five_minutes["down"] = down
    else:
        transmission_info_five_minutes["up"] += up
        transmission_info_five_minutes["down"] += down
    if statistics['transRateKBUpMax'] < up:
        statistics['transRateKBUpMax'] = up
    if statistics['transRateKBDownMax'] < down:
        statistics['transRateKBDownMax'] = down
    if statistics['transRateKBUpMin'] > up:
        statistics['transRateKBUpMin'] = up
    if statistics['transRateKBDownMin'] > down:
        statistics['transRateKBDownMin'] = down

    trans_count += 1


def report(context):
    global last_message_id
    global transmission_info_five_minutes
    global statistics
    global trans_count
    for user in allowed_users:
        if len(last_message_id.keys()) > 0:
            bot.delete_message(chat_id=user, message_id=last_message_id[user])
        message_id_obj = bot.sendMessage(chat_id=user, text=f"Mean-UP: {(transmission_info_five_minutes['up'] / trans_count):.2f} KB"
                                                            f"\nMean_Down: {(transmission_info_five_minutes['down'] / trans_count):.2f} KB"
                                                            f"\nIs connected: {router_status.is_connected}"
                                                            f"\nIs linked: {router_status.is_linked}")
        last_message_id[user] = message_id_obj.message_id
    write_to_database()
    transmission_info_five_minutes = {}
    statistics = {'transRateKBUpMax': 0, 'transRateKBDownMax': 0, 'transRateKBUpMin': 0, 'transRateKBDownMin': 0}
    trans_count = 0


def gather(context):
    global host_list
    global gather_message_id
    cur_hosts = {host['mac']: host['name'] for host in router_host.get_hosts_info() if host['status']}
    missing_hosts = set(host_list.keys()) - set(cur_hosts.keys())
    new_hosts = set(cur_hosts.keys()) - set(host_list.keys())
    if len(missing_hosts) > 0:
        for user in allowed_users:
            bot.sendMessage(chat_id=user,
                                text=f"Following devices left the network:\n"
                                f" {','.join(list(host_list[f] for f in missing_hosts))}")
    if len(new_hosts) > 0:
        for user in allowed_users:
            bot.sendMessage(chat_id=user,
                            text=f"Following devices joined the network:\n"
                                f" {','.join(list(cur_hosts[f] for f in new_hosts))}")
    host_list = cur_hosts


# Telegram functions
def start(update, context):
    global router_model
    update.message.reply_text(
        f'Hello {update.message.from_user.first_name}. Welcome in the information chat of the Router {router_status.modelname}')


def help(update, context):
    update.message.reply_text('The following commands are implemented:\n'
                              '\t- /start  Starts the bot\n'
                              '\t- /check [ip, ipv6, uptime]\n'
                              '\t- /getnewip')


def check(update, context):
    c_status = update.message.text.split(" ", 1)[1]
    if c_status == 'ip':
        message = f'External IPv4: {router_status.external_ip}'
    elif c_status == 'ipv6':
        message = f'External IPv6: {router_status.external_ipv6}'
    else:
        message = f'Current up-time: {router_status.str_uptime}'
    update.message.reply_text(message)


def get_new_ip(update, context):
    router_status.reconnect()
    update.message.reply_text(f'External IPv4: {router_status.external_ip}')


updater = Updater(key, use_context=True)
bot = Bot(token=key)

updater.dispatcher.add_handler(CommandHandler('start', start, Filters.user(allowed_users)))
updater.dispatcher.add_handler(CommandHandler('help', help, Filters.user(allowed_users)))
updater.dispatcher.add_handler(CommandHandler('check', check, Filters.user(allowed_users)))
updater.dispatcher.add_handler(CommandHandler('getnewip', get_new_ip, Filters.user(allowed_users)))

jobs = updater.job_queue
job_report = jobs.run_repeating(report, interval=300, first=300)
job_gather = jobs.run_repeating(gather, interval=10, first=0)
job_gather_trans = jobs.run_repeating(gather_transmission_informations, interval=1, first=0)
updater.start_polling()
updater.idle()
