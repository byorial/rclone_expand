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
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except ImportError:
    os.system('pip install gspread oauth2client')
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

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
from .model import ModelSetting, WSModelItem, ListModelItem
from .logic_gclone import LogicGclone

#########################################################


class LogicGSheet(object):
    
    @staticmethod
    def process_ajax(sub, req):
        try:
            if sub == 'copy':
                id = req.form['id']
                ret = LogicGSheet.gclone_copy(id)
                return jsonify(ret)
            elif sub == 'search_gsheet':
                doc_id = req.form['gsheet_doc_id']
                ret = LogicGSheet.search_gsheet(doc_id)
                return jsonify(ret)
            elif sub == 'register_gsheet':
                #logger.debug(req.form)
                wsinfo = req.form
                ret = LogicGSheet.register_gsheet(wsinfo)
                return jsonify(ret)
            elif sub == 'delete_ws':
                id= req.form['id']
	    	entity = WSModelItem.get(id)

		if entity is None:
                    ret = {'ret':False, 'data':'항목을 찾을 수 없습니다.'}
                    return jsonify(ret)

                WSModelItem.delete(entity.id)
                ret = {'ret': True, 'data':'Success'}
                return jsonify(ret)
            elif sub == 'web_list':
                ret = WSModelItem.web_list(req)
                return jsonify(ret)
            elif sub == 'load_items':
                id= req.form['id']
                ret = LogicGSheet.load_items(id)
                return jsonify(ret)
            elif sub == 'get_size':
                id= req.form['id']
                ret = LogicGSheet.get_size(id)
                return jsonify(ret)
            elif sub == 'ws_list':
                try:
                    sheet_id = req.form['sheet_id']
                    ret = ListModelItem.item_list(req, sheet_id=sheet_id)
                except:
                    ret = ListModelItem.item_list(req)
                return jsonify(ret)
            elif sub == 'item_list':
                ret = ListModelItem.item_list(req)
                return jsonify(ret)
            elif sub == 'delete_item':
                id= req.form['id']
                ret = LogicGSheet.delete_item(id)
                return jsonify(ret)
            elif sub == 'reset_db':
                reqtype = req.form['type']
                ret = LogicGSheet.reset_db(reqtype)
                return jsonify(ret)

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret = {'ret':False, 'data':'Exception! 로그를 확인하세요'}
            return jsonify(ret)
    
    @staticmethod
    def validate_sheet(ws):
        cols = ws.row_values(1)
        if u'제목' in cols and u'폴더 ID' in cols and u'분류' in cols:
            return True
        return False

    @staticmethod
    def get_first_json():
        import glob
        accounts_dir = ModelSetting.get('path_accounts')
        sa_files = glob.glob(os.path.join(accounts_dir, '*.json'))
        if len(sa_files) == 0:
            return None
        first_json = os.path.join(accounts_dir, sa_files[0])
        return os.path.join(accounts_dir, sa_files[0])

    @staticmethod
    def search_gsheet(doc_id):
        try:
            ret = []
            logger.debug('start to search_gsheet: %s', doc_id)
            json_file = LogicGSheet.get_first_json()
            if json_file is None:
                logger.error('failed to get json file. please check json file in (%s)', ModelSetting.get('path_accounts'))
                return ret
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            doc_url = 'https://docs.google.com/spreadsheets/d/{doc_id}'.format(doc_id=doc_id)

            credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)
            gsp = gspread.authorize(credentials)
            doc = gsp.open_by_url(doc_url)
            for ws in doc.worksheets():
                if LogicGSheet.validate_sheet(ws):
                    ret.append({'doc_id':doc.id, 'doc_title':doc.title, 'doc_url':doc_url,
                        'ws_id':ws.id, 'ws_title':ws.title})
            return ret

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def register_gsheet(info):
        try:
            #logger.debug(info)
            entity = WSModelItem.create(info)
            if entity is None:
                return {'ret':False, 'data':'이미 등록된 시트입니다'}

            return {'ret':True, 'data':'등록되었습니다.'}

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return 'Failed'

    @staticmethod
    def get_worksheet(doc, wsmodel_id):
        try:
            for ws in doc.worksheets():
                if ws.id == wsmodel_id:
                    return ws
            return None
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def load_items(wsmodel_id):
        try:
            ret = []
            wsentity = WSModelItem.get(wsmodel_id)
            if wsentity is None:
                return None

            # 목록이 삭제된 경우 업데이트
            if wsentity.total_count > 0:
                wsentity.total_count = ListModelItem.get_total_count(wsentity.id)
                wsentity.copy_count = ListModelItem.get_copy_count(wsentity.id)
                wsentity.save()

            doc_id = wsentity.doc_id
            ws_id  = wsentity.ws_id
            logger.debug('start to get item from gsheet: %s, ws:%d', doc_id, ws_id)
            json_file = LogicGSheet.get_first_json()
            if json_file is None:
                logger.error('failed to get json file. please check json file in (%s)', ModelSetting.get('path_accounts'))
                return ret
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            doc_url = wsentity.doc_url

            credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)
            gsp = gspread.authorize(credentials)
            doc = gsp.open_by_url(doc_url)
            ws = LogicGSheet.get_worksheet(doc, ws_id)
            count = 0
            for r in ws.get_all_records(head=1):
                try:
                    # 폴더ID, 분류가 없는 경우 제외
                    if r[u'분류'] == '' or r[u'폴더 ID'] == '':
                        continue

                    # 파일수, 사이즈가 없는 경우 예외처리
                    if r[u'파일수'] == '': obj_num = 0
                    else: obj_num = int(r[u'파일수'])
                    if r[u'사이즈'] == '': str_size = '-'
                    else: str_size = r[u'사이즈']

                    # 파일수0, 사이즈 0Bytes인경우 스킵
                    if obj_num == 0 and str_size == u'0 Bytes':
                        continue

                    info = {'sheet_id':wsmodel_id, 
                            'title':r[u'제목'], 
                            'folder_id':r[u'폴더 ID'], 
                            'category':r[u'분류'], 
                            'title2':r[u'제목 매핑'],
                            'obj_num':obj_num,
                            'str_size':str_size}

                    entity = ListModelItem.create(info)
                    if entity is None:
                        logger.info('already exist item(folder_id:%s)', info['folder_id'])
                        continue
                    count += 1

                except KeyError:
                    logger.error('failed to get item info')
                    logger.error(r)
                    continue

            wsentity.updated_time = datetime.now()
            wsentity.total_count += count
            wsentity.save()
            ret = {'ret':True, 'data':'{count} 항목을 추가하였습니다.'.format(count=count)}
            return ret

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_size(id):
        try:
            entity = ListModelItem.get(id)
            if entity is None:
                return {'ret':False, 'data':'유효한 아이템이 없습니다'}

            command = [ModelSetting.get('gclone_path'),
                    '--config',
                    ModelSetting.get('gclone_config_path'),
                    'size',
                    'gc:{%s}' % entity.folder_id]

            data = SystemLogicCommand.execute_command_return(command)
            if data.find('Failed') > 0:
                logger.error('failed to get size! (%s)' % (''.join(data)))
                return {'ret':False, 'data': ''.join(data)}

            data = data.split('\n')
            entity.obj_num = int(data[0].split(':')[1].strip())
            entity.str_size = data[1].split(':')[1].split('(')[0].strip()
            logger.debug('getsize: folder_id:%s obj_num: %d, size: %s', entity.folder_id, entity.obj_num, entity.str_size)
            entity.save()
            info_str = '<br>파일수: {obj_num}<br>사이즈: {str_size}'.format(obj_num=entity.obj_num, str_size=entity.str_size)
            # TODO: thread - 시트의 파일 정보 업데이트 
            def func():
                ret = LogicGSheet.update_size(entity.id)

            thread = threading.Thread(target=func, args=())
            thread.setDaemon(True)
            thread.start()            

            return {'ret':True, 'data':info_str}
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return {'ret':False, 'data':'{e}'.format(e=e)}

    @staticmethod
    def get_user_copy_dest(category):
        try:
            if ModelSetting.get_bool('use_user_setting'):
                rule_list = ModelSetting.get('user_copy_dest_rules').split('\n')
                for rule in rule_list:
                    orig, converted = rule.split('|')
                    if orig.endswith('*'): orig = orig.replace('*','')
                    logger.debug('orig(%s), category(%s)', orig, category)
                    if category.startswith(orig): return converted

            return category
                
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def get_int_size(str_size):
        try:
            measer = {u'Bytes':1, u'KBytes':1000, u'MBytes':1000000, u'GBytes':1000000000, u'TBytes':1000000000000}
            num, unit = str_size.split(u' ')
            size = float(num) * measer[unit]
            return int(size)
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def update_size(entity_id):
        try:
            entity = ListModelItem.get(entity_id)
            wsentity = WSModelItem.get(entity.sheet_id)

	    doc_id = wsentity.doc_id
            ws_id  = wsentity.ws_id
            logger.debug('start to get item from gsheet: %s, ws:%d', doc_id, ws_id)
            json_file = LogicGSheet.get_first_json()
            if json_file is None:
                logger.error('failed to get json file. please check json file in (%s)', ModelSetting.get('path_accounts'))
                return ret
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            doc_url = wsentity.doc_url
            credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)
            gsp = gspread.authorize(credentials)
            doc = gsp.open_by_url(doc_url)
            ws = LogicGSheet.get_worksheet(doc, ws_id)
            cols = ws.row_values(1)

            index_size = cols.index(u'사이즈')
            index_obj_num = cols.index(u'파일수')
            cell = ws.find(entity.folder_id)

            ws.update_cell(cell.row, index_size+1, entity.str_size)
            ws.update_cell(cell.row, index_obj_num+1, entity.obj_num)

        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def gclone_copy(id):
        try:
            entity = ListModelItem.get(id)
            if entity is None:
                return {'ret':False, 'data':'유효한 아이템이 없습니다'}

            category = LogicGSheet.get_user_copy_dest(entity.category)
            logger.debug('category: %s -> %s', entity.category, category)

            from gd_share_client.logic_user import LogicUser
            my_remote = LogicUser.get_my_copy_path('gsheet', category)

            if ModelSetting.get_bool('use_user_setting'):
                dest_folder = entity.title2 if entity.title2 != u'' else entity.title
                gcstring = 'gc:{%s}|%s/%s' % (entity.folder_id, my_remote, dest_folder)
            else:
                dest_folder = entity.category + '/' + entity.title2 if entity.title2 != u'' else entity.title
                gcstring = 'gc:{%s}|%s/%s' % (entity.folder_id, "gc:{}", dest_folder)

            LogicGclone.queue_append([gcstring])
            entity.copied_time = datetime.now()

            # 처음 복사하는 경우만 시트정보에 카운트 갱신
            if entity.copy_count == 0:
                wsentity = WSModelItem.get(entity.sheet_id)
                if wsentity is not None:
                    wsentity.copy_count += 1
                    wsentity.save()
            entity.copy_count += 1
            entity.save()
            return {'ret':True, 'data':'큐에 추가하였습니다.'}

        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def delete_item(id):
        try:
	    entity = ListModelItem.get(id)
	    if entity is None:
                return {'ret':False, 'data':'항목을 찾을 수 없습니다.'}

            wsentity = WSModelItem.get(entity.sheet_id)
            if wsentity is not None:
                wsentity.total_count -= 1
                if entity.copy_count > 0: wsentity.copy_count -= 1
                wsentity.save()

            ListModelItem.delete(entity.id)
            data = '아이템항목(ID:{id})을 삭제하였습니다.'.format(id=entity.id)
            ret = {'ret': True, 'data':data}
            return ret
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return {'ret':False, 'data':'Exception'}

    @staticmethod
    def reset_db(reqtype):
        try:
            if reqtype == "all":
                c1 = db.session.query(WSModelItem).delete()
                c2 = db.session.query(ListModelItem).delete()
                db.session.commit()
                data = '{c1}개의 시트와 {c2}개의 아이템을 삭제하였습니다.'.format(c1=c1, c2=c2)
            elif reqtype  == "all_ws":
                c1 = db.session.query(WSModelItem).delete()
                db.session.commit()
                data = '{c1}개의 시트를 삭제하였습니다.'.format(c1=c1)
            elif reqtype  == "all_item":
                c1 = db.session.query(ListModelItem).delete()
                db.session.commit()
                data = '{c1}개의 아이템을 삭제하였습니다.'.format(c1=c1)
            elif reqtype  == "copied_item":
                c1 = db.session.query(ListModelItem).filter(ListModelItem.copy_count > 0).delete()
                db.session.commit()
                data = '{c1}개의 복사된 아이템을 삭제하였습니다.'.format(c1=c1)
            elif reqtype  == "no_item":
                from sqlalchemy import and_
                c1 = db.session.query(ListModelItem).filter(and_(ListModelItem.obj_num == 0, ListModelItem.str_size == '0 Bytes')).delete()
                db.session.commit()
                data = '{c1}개의 불량 아이템을 삭제하였습니다.'.format(c1=c1)
            ret = {'ret':True, 'data':data}
            return ret
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return {'ret':False, 'data':''}
