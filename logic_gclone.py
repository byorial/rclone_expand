# -*- coding: utf-8 -*-
#########################################################
# python
import os
from datetime import datetime
import traceback
import logging
import subprocess
import time
import re
import threading
import json
import platform
import shutil

# third-party
from flask import Blueprint, request, Response, send_file, render_template, redirect, jsonify

# sjva 공용
from framework import app, db, scheduler, path_app_root, celery, path_data, socketio
from framework.job import Job
from framework.util import Util, AlchemyEncoder
from framework.common.share import RcloneTool, Vars
from system.model import ModelSetting as SystemModelSetting
from framework.common.util import AESCipher
from system.logic_command import SystemLogicCommand
from rclone_expand.model import ModelSetting

# 패키지
from .plugin import logger, package_name
from .model import ModelSetting

#########################################################


class LogicGclone(object):
    
    @staticmethod
    def process_ajax(sub, req):
        try:
            if sub == 'start':
                ret = LogicGclone.start()
                return jsonify(ret)
            elif sub == 'stop':
                LogicGclone.current_data['user_stop'] = True
                ret = LogicGclone.kill()
                return jsonify(ret)
            elif sub == 'version':
                command = [ModelSetting.get('gclone_path'), 'version']
                if app.config['config']['is_py2']:
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                else:
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
                iter_arg =  b'' if app.config['config']['is_py2'] else ''
                ret = []
                with process.stdout:
                    for line in iter(process.stdout.readline, iter_arg):
                        ret.append(line)
                    process.wait() # wait for the subprocess to exit
                return jsonify(ret)
            elif sub == 'view_config':
                from framework.common.util import read_file
                data = read_file(ModelSetting.get('gclone_config_path'))
                return jsonify({'ret':True, 'data':data})
            elif sub == 'gen_config':
                default = '''
[gc]
type = drive
scope = drive
service_account_file = {first_json}
service_account_file_path = {accounts_dir}/
'''
                import glob
                accounts_dir = ModelSetting.get('path_accounts')
                sa_files = glob.glob(os.path.join(accounts_dir, '*.json'))
                if len(sa_files) == 0:
                    ret = {'ret':False, 'log:': u'json 파일이 없습니다.'}
                else:
                    first_json = os.path.join(accounts_dir, sa_files[0])
                    default = default.format(first_json=first_json, accounts_dir=accounts_dir)
                    logger.debug(default)
                    from framework.common.util import read_file, write_file
                    config_path = ModelSetting.get('gclone_config_path')
                    write_file(default, config_path)
                    ret = {'ret':True, 'data':read_file(config_path)}
                return jsonify(ret)
            elif sub == 'log_reset':
                LogicGclone.current_data['log'] = []
                return jsonify('')
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def process_api(sub, req):
        try:
            if sub == 'append':
                ret = {}
                cmd = req.form['cmd']
                tmp = ModelSetting.get('gclone_queue_list')
                if tmp.find(cmd) != -1:
                    ret['status'] = 'already_exist'
                else:
                    ret['status'] = LogicGclone.current_data['status']
                    LogicGclone.queue_append([cmd])
                    logger.debug('process_api:%s', ret)
                    logger.debug('process_api:%s', cmd)
                return jsonify(ret)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
 
    ###################
    current_process = None
    current_data = {'user_stop':False, 'status':'ready', 'command':''}

    trans_regexes = [
        r'Transferred\:\s*(?P<trans_data_current>(\d.*?|off))\s\/\s(?P<trans_total_size>\d.*?)\,\s*((?P<trans_percent>\d+)\%)?\-?\,\s*(?P<trans_speed>\d.*?)\,\sETA\s(((?P<rt_hour>\d+)h)*((?P<rt_min>\d+)m)*((?P<rt_sec>.*?)s)*)?\-?',
        r'Errors\:\s*(?P<error>\d+)',
        r'Checks\:\s*(?P<check_1>\d+)\s\/\s(?P<check_2>\d+)\,\s*(?P<check_percent>\d+)?\-?',
        r'Transferred\:\s*(?P<file_1>\d+)\s\/\s(?P<file_2>\d+)\,\s*((?P<file_percent>\d+)\%)?\-?',
        r'Elapsed\stime\:\s*((?P<r_hour>\d+)h)*((?P<r_min>\d+)m)*((?P<r_sec>.*?)s)*',
        r'\s*\*\s((?P<folder>.*)\/)?(?P<name>.*?)\:\s*(?P<percent>\d+)\%\s*\/(?P<size>\d.*?)\,\s*(?P<speed>\d.*?)\,\s*((?P<rt_hour>\d+)h)*((?P<rt_min>\d+)m)*((?P<rt_sec>.*?)s)*', 
        r'INFO\s*\:\s*((?P<folder>.*)\/)?(?P<name>.*?)\:\s*(?P<status>.*)'
    ]

    fclone_trans_regexes = [
        r'Transferred:\s*(?P<current>(\d.*?))\s*\/\s*(?P<total>\d.*?),\s*(?P<trans_percent>\-|\d.*?)(%)?,\s*(?P<bps>\d.*?Bytes/s)?,\s*ETA\s*((?P<eta1>\-)?|((?P<rt_hour>\d+)h)?((?P<rt_min>\d+)m)?((?P<rt_sec>.*?)s)?)$',
        r'Transferred:\s*(?P<file_1>(\d.*?))\s*\/\s*(?P<file_2>\d.*?),\s*(?P<file_percent>\-|\d.*?)(%)?,\s*(?P<fps>\d.*?Files/s)?,\s*ETA\s*((?P<eta1>\-)?|((?P<rt_hour>\d+)h)?((?P<rt_min>\d+)m)?((?P<rt_sec>.*?)s)?)$',
        r'Errors\:\s*(?P<error>\d+)',
        r'Checks\:\s*(?P<check_1>\d+)\s\/\s(?P<check_2>\d+)\,\s*(?P<check_percent>\d+)?\-?',
        r'Elapsed\stime\:\s*((?P<r_hour>\d+)h)*((?P<r_min>\d+)m)*((?P<r_sec>.*?)s)*',
        r'\s*\*\s((?P<folder>.*)\/)?(?P<name>.*?)\:\s*(?P<percent>\d+)\%\s*\/(?P<size>\d.*?)\,\s*(?P<speed>\d.*?)\,\s*((?P<rt_hour>\d+)h)*((?P<rt_min>\d+)m)*((?P<rt_sec>.*?)s)*', 
        r'INFO\s*\:\s*((?P<folder>.*)\/)?(?P<name>.*?)\:\s*(?P<status>.*)'
    ]


    @staticmethod
    def queue_append(queue_list):
        try:
            logger.debug(queue_list)
            new_queue_list = []
            for q in queue_list:
                src, tar = q.split('|')
                tmps = tar.split('/')
                if len(tmps) > 1:
                    for i in range(1, len(tmps)):
                        tmps[i] = Util.change_text_for_use_filename(tmps[i]).replace('   ', '  ').replace('  ', ' ').rstrip('.').strip()
                    new_queue_list.append('%s|%s/%s' % (src, tmps[0], '/'.join(tmps[1:])))
                else:
                    new_queue_list.append(q)

            logger.debug(new_queue_list)
            tmp = ModelSetting.get('gclone_queue_list')
            tmp += '\n' + '\n'.join(new_queue_list)
            ModelSetting.set('gclone_queue_list', tmp)
            socketio_callback('refresh_queue', ModelSetting.get('gclone_queue_list'))
            return LogicGclone.start()
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod 
    def start():
        try:
            if LogicGclone.current_data['status'] == 'is_running':
                return 'already_running'
            elif LogicGclone.current_data['status'] == 'ready':
                
                def func():
                    LogicGclone.current_data['status'] = 'is_running'
                    while True:
                        count = 0
                        job_list = ModelSetting.get_list('gclone_queue_list', '\n')
                        for job in job_list:
                            try:
                                if LogicGclone.current_data['user_stop']:
                                    break
                                tmp = job.split('#')[0].split('|')
                                if len(tmp) == 2:
                                    target = tmp[1].strip()
                                    target = target.replace('{}', '{%s}' % ModelSetting.get('gclone_default_folderid'))
                                    if target.find('{}') != -1:
                                        continue
                                    if target.find(':') == -1:
                                        continue
                                    return_code = LogicGclone.gclone_execute(tmp[0].strip(), target)
                                    # 0 정상
                                    logger.debug('return_code:%s', return_code)
                                    if return_code == 0:
                                        tmp2 = ModelSetting.get('gclone_queue_list')
                                        for t in tmp2.split('\n'):
                                            if t.strip().startswith('%s|%s' % (tmp[0], tmp[1])):
                                                ModelSetting.set('gclone_queue_list', tmp2.replace(t, ''))
                                                socketio_callback('refresh_queue', ModelSetting.get('gclone_queue_list'))
                                        count += 1
                            except Exception as e: 
                                logger.error('Exception:%s', e)
                                logger.error(traceback.format_exc())
                        if LogicGclone.current_data['user_stop']:
                            break
                        if count == 0:
                            break
                    LogicGclone.current_data['status'] = 'ready'
                    LogicGclone.current_data['user_stop'] = False
                    data = {'type':'success', 'msg' : u'gclone 작업을 완료하였습니다.'}
                    socketio.emit("notify", data, namespace='/framework', broadcast=True)
                thread = threading.Thread(target=func, args=())
                thread.setDaemon(True)
                thread.start()
                return 'success'

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def gclone_execute(source, target):
        
            #./gclone --config ./gclone.conf copy gc:{1Qs6xsVJF7TkMk00s6W28HjdZ8onx2C4O} gc:{1BhTY6WLPRUkqKukNtQTIDMyjLO_UKMzP} --drive-server-side-across-configs -vvv --progress --tpslimit 3 --transfers 3 --stats 1s
        try:
            data = {'type':'success', 'msg' : u'Target:%s 작업을 시작합니다.' % target}
            socketio.emit("notify", data, namespace='/framework', broadcast=True)


            command = [
                ModelSetting.get('gclone_path'),
                '--config', ModelSetting.get('gclone_config_path'),
                'copy', source, target
            ]
            is_fclone = LogicGclone.is_fclone()
            # fclone의 경우 log-level 강제설정
            if is_fclone:
                command += ['--stats','1s','--log-level','NOTICE','--stats-log-level','NOTICE']
            else:
                command += ModelSetting.get_list('gclone_fix_option', ' ')

            command += ModelSetting.get_list('gclone_user_option', ' ')
            logger.debug(command)         
            if app.config['config']['is_py2']:    
                LogicGclone.current_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
            else:
                LogicGclone.current_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            
            LogicGclone.current_data['command'] = ' '.join(command)
            LogicGclone.current_data['log'] = []
            LogicGclone.current_data['files'] = []

            LogicGclone.trans_callback('start')
            if is_fclone:
                LogicGclone.current_log_thread = threading.Thread(target=LogicGclone.fclone_log_thread_fuction, args=())
            else: 
                LogicGclone.current_log_thread = threading.Thread(target=LogicGclone.log_thread_fuction, args=())
            LogicGclone.current_log_thread.start()
            logger.debug('normally process wait()')
            ret = LogicGclone.current_process.wait()
            LogicGclone.current_process = None
            return ret
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return 'fail'


    @staticmethod
    def trans_callback(cmd, data=None):
        try:
            if data is not None:
                if isinstance(data, FileFinished):
                    pass
                elif isinstance(data, TransStatus):
                    LogicGclone.current_data['ts'] = data.__dict__
            socketio_callback(cmd, LogicGclone.current_data)
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def log_thread_fuction():
        with LogicGclone.current_process.stdout:
            ts = None
            iter_arg =  b'' if app.config['config']['is_py2'] else ''
            for line in iter(LogicGclone.current_process.stdout.readline, iter_arg):
                line = line.strip()
                try:
                    try:
                        line = line.decode('utf-8')
                    except Exception as e: 
                        try:
                            line = line.decode('cp949')
                        except Exception as e: 
                            pass
                    #logger.debug('>>>> %s', line)
                    if line == '' or  line.startswith('Checking'):
                        continue
                    if line.endswith('INFO  :'):
                        continue
                    if line.startswith('Deleted:'):
                        continue
                    if line.startswith('Transferring:'):
                        ts.files = []
                        continue
                    match = re.compile(LogicGclone.trans_regexes[0]).search(line)
                    if match:
                        if ts is not None:
                            LogicGclone.trans_callback('status', ts)
                        ts = TransStatus()
                        ts.trans_data_current = match.group('trans_data_current')
                        ts.trans_total_size = match.group('trans_total_size')
                        ts.trans_percent = match.group('trans_percent') if 'trans_percent' in match.groupdict() else '0'
                        ts.trans_speed = match.group('trans_speed')
                        ts.rt_hour = match.group('rt_hour') if 'rt_hour' in match.groupdict() else '0'
                        ts.rt_min = match.group('rt_min') if 'rt_min' in match.groupdict() else '0'
                        ts.rt_sec = match.group('rt_sec') if 'rt_sec' in match.groupdict() else '0'
                        continue
                    match = re.compile(LogicGclone.trans_regexes[1]).search(line)
                    if match:
                        ts.error = match.group('error')
                        continue
                    match = re.compile(LogicGclone.trans_regexes[2]).search(line)
                    if match:
                        ts.check_1 = match.group('check_1')
                        ts.check_2 = match.group('check_2')
                        ts.check_percent = match.group('check_percent') if 'check_percent' in match.groupdict() else '0'
                        continue
                    match = re.compile(LogicGclone.trans_regexes[3]).search(line)
                    if match:
                        ts.file_1 = match.group('file_1')
                        ts.file_2 = match.group('file_2')
                        ts.file_percent = match.group('file_percent') if 'file_percent' in match.groupdict() else '0'
                        continue
                    match = re.compile(LogicGclone.trans_regexes[4]).search(line)
                    if match:
                        ts.r_hour = match.group('r_hour') if 'r_hour' in match.groupdict() else '0'
                        ts.r_min = match.group('r_min') if 'r_min' in match.groupdict() else '0'
                        ts.r_sec = match.group('r_sec') if 'r_sec' in match.groupdict() else '0'
                        continue
                    
                    
                    match = re.compile(LogicGclone.trans_regexes[5]).search(line)
                    if match:
                        #ts.files.append(TransFile.get(match).__dict__)
                        #LogicGclone.set_file(match)
                        continue
                    if line.startswith('Renamed:'):
                        continue
                    if line.find('INFO :') == -1:
                        LogicGclone.current_data['log'].append(line)
                        if len(LogicGclone.current_data['log']) == 1000:
                            LogicGclone.current_data['log'] = LogicGclone.current_data['log'][100:]
                        LogicGclone.trans_callback('log')
                    match = re.compile(LogicGclone.trans_regexes[6]).search(line)
                    if match:
                        LogicGclone.trans_callback('files', FileFinished(match))
                        continue
                    #logger.debug('NOT PROCESS : %s', line)       
                except Exception as e:
                    logger.error('Exception:%s', e)
                    logger.error(traceback.format_exc())
            logger.debug('rclone log thread end')
        logger.debug(str(ts))
        LogicGclone.trans_callback('status', ts)

    @staticmethod
    def fclone_log_thread_fuction():
        with LogicGclone.current_process.stdout:
            ts = None
            iter_arg =  b'' if app.config['config']['is_py2'] else ''
            for line in iter(LogicGclone.current_process.stdout.readline, iter_arg):
                line = line.strip()
                try:
                    try:
                        line = line.decode('utf-8')
                    except Exception as e: 
                        try:
                            line = line.decode('cp949')
                        except Exception as e: 
                            pass
                    if line == '' or  line.startswith('Checking'):
                        continue
                    if line.endswith('INFO  :'):
                        continue
                    if line.startswith('Deleted:'):
                        continue
                    if line.startswith('Transferring:'):
                        ts.files = []
                        continue
                    match = re.compile(LogicGclone.fclone_trans_regexes[0]).search(line)
                    if match:
                        #logger.debug(match.groupdict())
                        if ts is not None:
                            LogicGclone.trans_callback('status', ts)
                        ts = TransStatus()
                        ts.trans_data_current = match.group('current')
                        ts.trans_total_size = match.group('total')
                        ts.trans_percent = match.group('trans_percent') if 'trans_percent' in match.groupdict() else '0'
                        ts.trans_speed = match.group('bps')
                        ts.rt_hour = match.group('rt_hour') if 'rt_hour' in match.groupdict() else '0'
                        ts.rt_min = match.group('rt_min') if 'rt_min' in match.groupdict() else '0'
                        ts.rt_sec = match.group('rt_sec') if 'rt_sec' in match.groupdict() else '0'
                        continue
                    match = re.compile(LogicGclone.fclone_trans_regexes[1]).search(line)
                    if match:
                        #logger.debug(match.groupdict())
                        #ts.trans_speed = ' / '+ match.group('fps') # not use
                        ts.file_1 = match.group('file_1')
                        ts.file_2 = match.group('file_2')
                        ts.file_percent = match.group('file_percent') if 'file_percent' in match.groupdict() else '0'
                        ts.check_1 = ts.file_1
                        ts.check_2 = ts.file_2
                        ts.check_percent = ts.file_percent
                        continue
                    match = re.compile(LogicGclone.fclone_trans_regexes[2]).search(line)
                    if match:
                        ts.error = match.group('error')
                        logger.error('Errors: %s', ts.error)
                        continue
                    match = re.compile(LogicGclone.fclone_trans_regexes[4]).search(line)
                    if match:
                        ts.r_hour = match.group('r_hour') if 'r_hour' in match.groupdict() else '0'
                        ts.r_min = match.group('r_min') if 'r_min' in match.groupdict() else '0'
                        ts.r_sec = match.group('r_sec') if 'r_sec' in match.groupdict() else '0'
                        continue

                    # 로그를 많이 쏘면 SJVA가 뻗음
                    """
                    if line.find('INFO :') == -1:
                        LogicGclone.current_data['log'].append(line)
                        if len(LogicGclone.current_data['log']) == 1000:
                            LogicGclone.current_data['log'] = LogicGclone.current_data['log'][100:]
                        LogicGclone.trans_callback('log')
                    """

                    # 무시
                    match = re.compile(LogicGclone.fclone_trans_regexes[5]).search(line)
                    if match: 
                        #logger.debug('>>>> %s', line)
                        continue
                    match = re.compile(LogicGclone.fclone_trans_regexes[6]).search(line)
                    # 발생안함
                    if match:
                        LogicGclone.trans_callback('files', FileFinished(match))
                        continue

                    #logger.debug('NOT PROCESS : %s', line)       
                except Exception as e:
                    logger.error('Exception:%s', e)
                    logger.error(traceback.format_exc())
            logger.debug('rclone log thread end')
        LogicGclone.trans_callback('status', ts)






    @staticmethod
    def kill():
        try:
            if LogicGclone.current_process is not None and LogicGclone.current_process.poll() is None:
                import psutil
                process = psutil.Process(LogicGclone.current_process.pid)
                for proc in process.children(recursive=True):
                    proc.kill()
                process.kill()
                return 'success'
            return 'not_running'
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return 'fail'
        finally:
            LogicGclone.current_process = None


    @staticmethod
    def is_fclone():
        try:
            command = [ModelSetting.get('gclone_path'), 'version']
            if app.config['config']['is_py2']:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
            else:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            ret = []
            iter_arg =  b'' if app.config['config']['is_py2'] else ''
            with process.stdout:
                for line in iter(process.stdout.readline, iter_arg):
                    if line.find('fclone') != -1: return True
            return False
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())








    #################################################################










class TransStatus(object):
    def __init__(self):
        self.trans_data_current = \
        self.trans_total_size = \
        self.trans_percent = \
        self.trans_speed = \
        self.rt_hour = self.rt_min = self.rt_sec = \
        self.error = \
        self.check_1 = \
        self.check_2 = \
        self.check_percent = \
        self.file_1 = \
        self.file_2 = \
        self.file_percent = \
        self.r_hour = self.r_min = self.r_sec = ""
        #self.files = []






class FileFinished(object):
    def __init__(self, match):
        self.folder = match.group('folder') if 'folder' in match.groupdict() else ''
        self.name = match.group('name')
        self.status = match.group('status')







#########################################################
# socketio / sub
#########################################################
sid_list = []
plex_log = ''
@socketio.on('connect', namespace='/%s/gclone' % package_name)
def connect():
    try:
        logger.debug('socket_connect')
        sid_list.append(request.sid)
        #socketio_callback('start', LogicGclone.current_data)
        socketio_callback('connect',LogicGclone.current_data)
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())


@socketio.on('disconnect', namespace='/%s/gclone' % package_name)
def disconnect():
    try:
        sid_list.remove(request.sid)
        logger.debug('socket_disconnect')
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())


def socketio_callback(cmd, data, encoding=True):
    if sid_list:
        if encoding:
            data = json.dumps(data, cls=AlchemyEncoder)
            data = json.loads(data)
        #logger.debug(cmd)
        #logger.debug(data)
        socketio.emit(cmd, data, namespace='/%s/gclone' % package_name, broadcast=True)
        
