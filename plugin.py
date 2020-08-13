# -*- coding: utf-8 -*-
#########################################################
# python
import os
import traceback
import json
import glob

# third-party
from flask import Blueprint, request, Response, send_file, render_template, redirect, jsonify, session, send_from_directory 
from flask_socketio import SocketIO, emit, send
from flask_login import login_user, logout_user, current_user, login_required

# sjva 공용
from framework.logger import get_logger
from framework import app, db, scheduler, path_data, socketio, check_api
from framework.util import Util
from system.model import ModelSetting as SystemModelSetting

# 패키지
package_name = __name__.split('.')[0]
logger = get_logger(package_name)

from .model import ModelSetting
from .logic import Logic
from .logic_autorclone import LogicAutoRclone
from .logic_gclone import LogicGclone
#########################################################


blueprint = Blueprint(package_name, package_name, url_prefix='/%s' %  package_name, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

menu = {
    'main' : [package_name, 'Rclone Expand'],
    'sub' : [
        ['autorclone', 'AutoRclone'], ['gclone', 'Gclone'], ['log', '로그']
    ],
    'category' : 'service',
    'sub2' : {
        'autorclone' : [
            ['setting', '설정']
        ],
        'gclone' : [
            ['setting', '설정'], ['command', '작업'], 
        ]
    }

}

plugin_info = {
    'version' : '0.1.0.0',
    'name' : 'rclone_extend',
    'category_name' : 'service',
    'developer' : 'soju6jan',
    'description' : 'Rclone Expand',
    'home' : 'https://github.com/soju6jan/rclone_expand',
    'more' : '',
}

def plugin_load():
    Logic.plugin_load()

def plugin_unload():
    Logic.plugin_unload()

def process_telegram_data(data):
    pass


#########################################################
# WEB Menu   
#########################################################
@blueprint.route('/')
def home():
    return redirect('/%s/gclone' % package_name)

@blueprint.route('/<sub>', methods=['GET', 'POST'])
@login_required
def first_menu(sub): 
    try:
        if sub == 'autorclone':
            return redirect('/%s/%s/setting' % (package_name, sub))
        elif sub == 'gclone':
            return redirect('/%s/%s/command' % (package_name, sub))
        elif sub == 'log':
            return render_template('log.html', package=package_name)
        return render_template('sample.html', title='%s - %s' % (package_name, sub))
    except Exception as e:
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())


@blueprint.route('/<sub>/<sub2>')
@login_required
def second_menu(sub, sub2):
    try:
        arg = ModelSetting.to_dict()
        arg['sub'] = sub
        if sub == 'autorclone':
            if sub2 == 'setting':
                arg['autorclone_credentials_status'] = os.path.exists(ModelSetting.get('path_credentials'))
                arg['autorclone_credentials_status_str'] = 'credentials 파일이 있습니다.' if arg['autorclone_credentials_status'] else 'credentials 파일이 없습니다.'
                arg['autorclone_token_status'] = os.path.exists(ModelSetting.get('path_token'))
                arg['autorclone_token_status_str'] = 'API 토큰이 있습니다.' if arg['autorclone_token_status'] else 'API 토큰이 없습니다.'
                arg['autorclone_sa_count'] = len(glob.glob(os.path.join(ModelSetting.get('path_accounts'), '*.json')))
                try:
                    project_id = json.loads(open(arg['path_credentials'],'r').read())['installed']['project_id']
                    arg['api_use1'] = 'https://console.developers.google.com/apis/library/serviceusage.googleapis.com?project=%s' % project_id
                    arg['api_use2'] = 'https://console.developers.google.com/apis/library/iam.googleapis.com?project=%s' % project_id
                except:
                    arg['api_use1'] = arg['api_use2'] = ''
                return render_template('{package_name}_{sub}_{sub2}.html'.format(package_name=package_name, sub=sub, sub2=sub2), arg=arg)
        elif sub == 'gclone':
            if sub2 == 'setting':
                return render_template('{package_name}_{sub}_{sub2}.html'.format(package_name=package_name, sub=sub, sub2=sub2), arg=arg)
            elif sub2 == 'command':
                return render_template('{package_name}_{sub}_{sub2}.html'.format(package_name=package_name, sub=sub, sub2=sub2), arg=arg)
        return render_template('sample.html', title='%s - %s' % (package_name, sub))
    except Exception as e:
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())
    

#########################################################
# For UI                                                          
#########################################################
@blueprint.route('/ajax/<sub>', methods=['GET', 'POST'])
@login_required
def ajax(sub):
    logger.debug('AJAX %s %s', package_name, sub)
    try:
        # global
        if sub == 'setting_save':
            ret = ModelSetting.setting_save(request)
            return jsonify(ret)
        elif sub == 'scheduler':
            sub = request.form['sub']
            go = request.form['scheduler']
            logger.debug('scheduler :%s', go)
            if go == 'true':
                Logic.scheduler_start(sub)
            else:
                Logic.scheduler_stop(sub)
            return jsonify(go)
        elif sub == 'reset_db':
            sub = request.form['sub']
            ret = Logic.reset_db(sub)
            return jsonify(ret)
        elif sub == 'one_execute':
            sub = request.form['sub']
            ret = Logic.one_execute(sub)
            return jsonify(ret)
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())  


@blueprint.route('/ajax/<sub>/<sub2>', methods=['GET', 'POST'])
@login_required
def second_ajax(sub, sub2):
    try:
        if sub == 'autorclone':
            return LogicAutoRclone.process_ajax(sub2, request)
        elif sub == 'gclone':
            return LogicGclone.process_ajax(sub2, request)
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())


@blueprint.route('/api/<sub>/<sub2>', methods=['GET', 'POST'])
@check_api
def second_api(sub, sub2):
    try:
        if sub == 'gclone':
            return LogicGclone.process_api(sub2, request)
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())

