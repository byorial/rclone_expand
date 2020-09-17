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
from .model import ModelSetting, WSModelItem, ListModelItem
from .logic_gclone import LogicGclone

#########################################################
class LogicGSheet(object):
    # for GoogleDrive APIs
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    credentials = None
    service = None
    
    @staticmethod
    @celery.task
    def scheduler_function():
        try:
            logger.info('GSheet Scheduler-function started')
            LogicGSheet.google_api_auth()

            for wsentity in WSModelItem.get_scheduled_list():
                if wsentity.is_running:
                    logger.info('SKIP: sheet_id(%d) is running', wsentity.id)
                    continue

                # reload items
                LogicGSheet.load_items(wsentity.id)

                def func():
                    ret = LogicGSheet.scheduled_copy(wsentity.id)

                thread = threading.Thread(target=func, args=())
                thread.setDaemon(True)
                thread.start()            

            logger.info('GSheet Scheduler-function ended')

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

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
            elif sub == 'ws_list':
                ret = WSModelItem.ws_list(req)
                return jsonify(ret)
            elif sub == 'one_execute':
                id= req.form['id']
                ret = LogicGSheet.scheduled_copy(id)
                return jsonify(ret)
            elif sub == 'load_items':
                id= req.form['id']
                def func():
                    time.sleep(1)
                    LogicGSheet.load_items(id)
                threading.Thread(target=func, args=()).start()

                ret = {'ret':True, 'data':'아이템 목록 갱신을 요청했습니다.'}
                return jsonify(ret)
            elif sub == 'get_size':
                id= req.form['id']
                ret = LogicGSheet.get_size(id)
                return jsonify(ret)
            elif sub == 'save_wsinfo':
                logger.debug(req.form)
                ret = LogicGSheet.save_wsinfo(req.form)
                return jsonify(ret)
            elif sub == 'delete_wsinfo':
                logger.debug(req.form)
                ret = LogicGSheet.delete_wsinfo(req.form)
                return jsonify(ret)
            elif sub == 'delete_items':
                logger.debug(req.form)
                ret = LogicGSheet.delete_items(req.form)
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
            elif sub == 'size_migration':
                ret = LogicGSheet.size_migration()
                return jsonify(ret)

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret = {'ret':False, 'data':'Exception! 로그를 확인하세요'}
            return jsonify(ret)
    
    @staticmethod
    def google_api_auth():
        json_file = LogicGSheet.get_random_json()
        try:
            from oauth2client.service_account import ServiceAccountCredentials
        except ImportError:
            os.system('pip install oauth2client')
            from oauth2client.service_account import ServiceAccountCredentials
        try:
            from googleapiclient.discovery import build
        except ImportError:
            os.system('pip install googleapiclient')
            from googleapiclient.discovery import build
            
        LogicGSheet.credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, LogicGSheet.scope)
        LogicGSheet.service = build('drive',  'v3', credentials=LogicGSheet.credentials)

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
    def get_random_json():
        import glob, random
        accounts_dir = ModelSetting.get('path_accounts')
        sa_files = glob.glob(os.path.join(accounts_dir, '*.json'))
        if len(sa_files) == 0:
            return None
        idx = int(random.random() * len(sa_files))
        return os.path.join(accounts_dir, sa_files[idx])

    @staticmethod
    def get_file_info(file_id):
        try:
            service = LogicGSheet.service
            finfo = service.files().get(fileId=file_id, fields="mimeType, size",
                    supportsTeamDrives=True,
                    supportsAllDrives=True).execute()
            return finfo
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def search_gsheet(doc_id):
        try:
            ret = []
            logger.debug('start to search_gsheet: %s', doc_id)
            json_file = LogicGSheet.get_first_json()
            if json_file is None:
                logger.error('failed to get json file. please check json file in (%s)', ModelSetting.get('path_accounts'))
                return []

            if doc_id.startswith(u'http'): doc_url = doc_id
            else: doc_url = 'https://docs.google.com/spreadsheets/d/{doc_id}'.format(doc_id=doc_id)
            logger.debug('url(%s)', doc_url)

            try:
                import gspread
            except ImportError:
                os.system('pip install gspread')
                import gspread

            gsp = gspread.authorize(LogicGSheet.credentials)
            doc = gsp.open_by_url(doc_url)
            for ws in doc.worksheets():
                if LogicGSheet.validate_sheet(ws):
                    ret.append({'doc_id':doc.id, 'doc_title':doc.title, 'doc_url':doc_url,
                        'ws_id':ws.id, 'ws_title':ws.title})
            return ret

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return []

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
                data = {'type':'warning', 'msg':'유효한 워크시트가 아닙니다.'}
                socketio.emit("notify", data, namespace='/framework', broadcate=True)
                return

            # 목록이 삭제된 경우 업데이트
            if wsentity.total_count > 0:
                wsentity.total_count = ListModelItem.get_total_count(wsentity.id)
                wsentity.copy_count = ListModelItem.get_copy_count(wsentity.id)
                wsentity.save()

            doc_id = wsentity.doc_id
            ws_id  = wsentity.ws_id
            logger.debug('start to get items from gsheet: %s, ws:%d', doc_id, ws_id)
            """
            json_file = LogicGSheet.get_first_json()
            if json_file is None:
                logger.error('failed to get json file. please check json file in (%s)', ModelSetting.get('path_accounts'))
                return ret
            """
            doc_url = wsentity.doc_url

            try:
                import gspread
            except ImportError:
                os.system('pip install gspread')
                import gspread

            gsp = gspread.authorize(LogicGSheet.credentials)
            doc = gsp.open_by_url(doc_url)
            ws = LogicGSheet.get_worksheet(doc, ws_id)
            count = 0
            scount = 0
            ucount = 0
            curr = 0
            all_records = ws.get_all_records(head=1)
            col_values  = ws.col_values(2)
            total = len(all_records)
            for r in all_records:
                #logger.debug(r)
                curr += 1
                try:
                    # 폴더ID, 분류가 없는 경우 제외
                    if r[u'분류'] == '' or r[u'폴더 ID'] == '':
                        scount += 1
                        continue
                    folder_id = r[u'폴더 ID']
                    byte_size = LogicGSheet.get_byte_size(r[u'사이즈'])
                    str_size  = LogicGSheet.get_str_size(byte_size)
                    obj_num   = LogicGSheet.get_obj_num(r[u'파일수'])
                    title     = r[u'제목']

                    entity = ListModelItem.get_entity_by_folder_id(folder_id)
                    if entity is not None:
                        if byte_size == entity.byte_size and obj_num == entity.obj_num:
                            scount += 1
                            continue

                    # 파일/폴더 구분
                    finfo = LogicGSheet.get_file_info(folder_id)
                    if finfo is None:
                        logger.error('failed to get info of %s', folder_id)
                        scount += 1
                        continue

                    mimetype = 0
                    if finfo['mimeType'] != "application/vnd.google-apps.folder":
                        mimetype = 1
                        logger.debug('INFO(%03d/%03d): %s: type(file), title(%s), size(%s), objnum(1)', curr, total, folder_id, title, str_size)
                    else:
                        logger.debug('INFO(%03d/%03d): %s: type(folder), title(%s), size(%s), objnum(%d)', curr, total, folder_id, title, str_size, obj_num)

                    # 파일수0, 사이즈 0Bytes인경우 스킵
                    if obj_num == 0 and (str_size == u'0 Bytes' or byte_size == 0) and str_size != '-':
                        scount += 1
                        continue

                    info = {'sheet_id':wsmodel_id, 
                            'title':r[u'제목'], 
                            'folder_id':r[u'폴더 ID'], 
                            'mimetype':mimetype,
                            'category':r[u'분류'], 
                            'title2':r[u'제목 매핑'],
                            'obj_num':obj_num,
                            'str_size':str_size,
                            'byte_size':byte_size}

                    entity = ListModelItem.get_entity_by_folder_id(info['folder_id'])
                    if entity is not None:
                        updated = ListModelItem.update_with_info(entity.id, info)
                        if updated: ucount += 1
                        else: scount += 1
                    else:
                        entity = ListModelItem.create(info)
                        if entity is None:
                            #logger.debug('already exist item(folder_id:%s)', info['folder_id'])
                            scount += 1
                            continue
                        count += 1

                except KeyError:
                    logger.error('failed to get item info')
                    logger.error(r)
                    continue

            wsentity.updated_time = datetime.now()
            wsentity.total_count += count
            wsentity.save()

            # 결과 notify
            data = {'type':'success', 'msg':'<strong>워크시트({ws})에 {count} 항목을 추가하였습니다</strong><br>(갱신: {ucount}, 스킵: {scount}건)'.format(ws=wsentity.doc_title, count=count, ucount=ucount, scount=scount)}
            socketio.emit("notify", data, namespace='/framework', broadcate=True)

            logger.info('{count} 항목을 추가하였습니다(갱신: {ucount}, 스킵: {scount}건)'.format(count=count, ucount=ucount, scount=scount))
            return

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def delete_wsinfo(req):
        try:
            sheet_id = int(req['sheet_id'])
            wsentity = WSModelItem.get(sheet_id)
            if wsentity is None:
                return {'ret':False, 'data':'유효한 아이템이 없습니다'}
            wsentity.delete(wsentity.id)
            return {'ret':True, 'data':'삭제하였습니다.'}
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return {'ret':False, 'data':'Exception'}


    @staticmethod
    def delete_items(req):
        try:
            sheet_id = int(req['sheet_id'])
            wsentity = WSModelItem.get(sheet_id)
            if wsentity is None:
                return {'ret':False, 'data':'유효한 아이템이 없습니다'}

            entities = ListModelItem.get_entities_by_wsid(sheet_id)
            for entity in entities:
                entity.delete(entity.id)

            wsentity.total_count = 0
            wsentity.save()

            logger.info('워크시트(%%s)에서 %d개의 아이템을 삭제하였습니다.', wsentity.doc_title, len(entities))
            return {'ret':True, 'data':'%d개의 아이템을 삭제하였습니다.' % len(entities)}
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return {'ret':False, 'data':'Exception'}

    @staticmethod
    def save_wsinfo(req):
        try:
            sheet_id = int(req['sheet_id'])
            in_schedule = True if req['ws_in_schedule'] == 'True' else False
            wsentity = WSModelItem.get(sheet_id)
            if wsentity is None:
                return {'ret':False, 'data':'유효한 아이템이 없습니다'}
            wsentity.in_schedule = in_schedule
            logger.debug('save_wsinfo: sheet_id(%d), in_schedule(%s)', wsentity.id, wsentity.in_schedule)
            wsentity.save()
            return {'ret':True, 'data':'저장하였습니다.'}
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return {'ret':False, 'data':'Exception'}

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
            entity.byte_size = LogicGSheet.get_byte_size(entity.str_size)
            entity.updated_time = datetime.now()
            logger.debug('getsize: folder_id:%s obj_num: %d, size: %s', entity.folder_id, entity.obj_num, entity.str_size)
            entity.save()
            info_str = '<br>파일수: {obj_num}<br>사이즈: {str_size}'.format(obj_num=entity.obj_num, str_size=entity.str_size)
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
                rule_list = ModelSetting.get_list('user_copy_dest_rules', '\n')
                for rule in rule_list:
                    orig, converted = rule.split('|')
                    if orig.endswith('*'): orig = orig.replace('*','')
                    #logger.debug('orig(%s), category(%s)', orig, category)
                    if category.upper().startswith(orig.upper()): return converted

            return category
                
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def get_byte_size(str_size):
        try:
            if str_size == u'': return 0
            if type(str_size) is int or type(str_size) is long:
                return int(str_size)

            str_size = str_size.replace(',','')
            if str_size.find('Bytes') == -1:
                return int(str_size)
            measer = {u'Bytes':1.0, u'KBytes':1000.0, u'kBytes':1000.0, u'MBytes':1000.0**2, u'GBytes':1000.0**3, u'TBytes':1000.0**4}
            num, unit = str_size.split(u' ')
            size = float(num) * measer[unit]
            return int(size)
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return 0


    @staticmethod
    def get_str_size(byte_size):
        try:
            if byte_size == 0: return u'-'
            measer = {u'Bytes':1.0, u'KBytes':1000.0, u'kBytes':1000.0, u'MBytes':1000.0**2, u'GBytes':1000.0**3, u'TBytes':1000.0**4}
            for k,v in sorted(measer.items(), key = lambda item: item[1], reverse=True):
                if byte_size >= v:
                   return str(round(byte_size / v, 2)) + ' ' + k 
            return str(byte_size)
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return u'-'


    @staticmethod
    def get_obj_num(str_obj_num):
        try:
            if str_obj_num == u'': return 0
            return int(str_obj_num)
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return 0

    @staticmethod
    def check_plex_condition(entity):
        try:
            if ModelSetting.get_int('plex_condition') == 0:
                return False
            
            rx_keyword = r'(?P<keyword>.*?)\s*?(\(|\[).*'
            rx_year = r'\((?P<year>\d{4})\)'
            title = entity.title2 if entity.title2 != '' else entity.title
            return False

            # TODO:
            """
            from plex import LogicNormal as PlexLogic
            return True
            """
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return '-'

    @staticmethod
    def scheduled_copy(sheet_id):
        try:
            wsentity = WSModelItem.get(sheet_id)
            wsentity.is_running = True
            wsentity.save()

            # COPY items
            succeed = 0
            failed = 0

            copy_mode = ModelSetting.get_int('copy_mode')
            if copy_mode == 0: return

            # keyword rule 적용: 미사용-너무느림
            #rules = ModelSetting.get_list('keyword_rules', '|') if copy_mode == 1 else ModelSetting.get_list('except_keyword_rules', '|')

            # TODO:Plex 연동저건에 따른 처리: 0 연동안함, 1: 있으면 skip, 2: 용량크면복사
            #plex_condition = ModelSetting.get_int('plex_condition')

            for entity in ListModelItem.get_schedule_target_items(sheet_id):
                # keyword rule 적용: 파일타입의 경우만
                if entity.mimetype == 1:
                    rules = ModelSetting.get_list('keyword_rules', '|') if copy_mode == 1 else ModelSetting.get_list('except_keyword_rules', '|')
                    copy_flag = True
                    for rule in rules:
                        copy_flag = False if copy_mode == 1 else True
                        if entity.title.find(rule) != -1:
                            copy_flag = not copy_flag
                            logger.debug('keyword(%s) is matched, copy_flag(%s)', rule, copy_flag)
                            break
                    if not copy_flag: continue

                # keyword rule 적용: 미사용-너무느림
                """ 
                from gd_share_client.model import ModelSetting as gscModelSetting
                remote_path = 'gc:{%s}' % entity.folder_id
                ret = RcloneTool.lsjson(gscModelSetting.get('rclone_path'), gscModelSetting.get('rclone_config_path'), remote_path)
                if len(ret) == 0: continue

                for f in ret:
                    mtype = f['MimeType']
                    if not mtype.startswith('video/'):
                        continue

                    fname = f['Name']
                    # copy_mode: 1-whitelist, 2-blacklist
                    for rule in rules:
                        copy_flag = False if copy_mode == 1 else True
                        if fname.find(rule) != -1:
                            copy_flag = not copy_flag
                            logger.debug('keyword(%s) is matched, copy_flag(%s)', rule, copy_flag)
                            break

                if not copy_flag: continue
                """
                # TODO: Plex 연동 조건에 따른 복사 처리: 20.09.10 
                #if not LogicGSeet.check_plex_condition(entity):
                    #continue

                logger.info('copy target: %s, %s, %s, %s', 
                        entity.title2 if entity.title2 != u"" else entity.title,
                        entity.folder_id,
                        entity.category,
                        entity.str_size)
                ret = LogicGSheet.gclone_copy(entity.id)

                logger.info(ret['data'])
                if ret['ret']: succeed += 1
                else: failed += 1

            total = succeed + failed
            logger.info('scheduled_copy: total(%d), succeed(%d), failed(%d)', total, succeed, failed)
            ret = {'ret':True, 'data':'copy result: total({total}), succeed({succeed}), failed({failed})'.format(total=total,succeed=succeed,failed=failed) }
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            ret = {'ret':False, 'data':'Exception'}
        finally:
            wsentity.is_running = False
            wsentity.save()
            return ret

    @staticmethod
    def update_size(entity_id):
        try:
            entity = ListModelItem.get(entity_id)
            wsentity = WSModelItem.get(entity.sheet_id)

	    doc_id = wsentity.doc_id
            ws_id  = wsentity.ws_id
            logger.debug('start to get item from gsheet: %s, ws:%d', doc_id, ws_id)
            json_file = LogicGSheet.get_randon_json()
            if json_file is None:
                logger.error('failed to get json file. please check json file in (%s)', ModelSetting.get('path_accounts'))
                return ret
            doc_url = wsentity.doc_url

            try:
                import gspread
            except ImportError:
                os.system('pip install gspread')
                import gspread

            gsp = gspread.authorize(LogicGSheet.credentials)
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
            #logger.debug(category)
            my_remote = LogicUser.instance.get_my_copy_path('gsheet', category)
            logger.debug('my_remote(%s)', my_remote)

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
            return {'ret':False, 'data':'Exception'}

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

            #ListModelItem.delete(entity.id)
            entity.excluded = 1
            entity.save()

            data = '아이템항목(ID:{id})을 삭제하였습니다.'.format(id=entity.id)
            ret = {'ret': True, 'data':data}
            return ret
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return {'ret':False, 'data':'Exception'}

    @staticmethod
    def ws_ir_init():
        WSModelItem.ws_ir_init()

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
                #c1 = db.session.query(ListModelItem).filter(ListModelItem.copy_count > 0).delete()
                query = db.session.query(ListModelItem).filter(ListModelItem.copy_count > 0)
                query = query.filter(ListModelItem.excluded == 0)
                entities = query.all()
                for e in entities:
                    e.excluded = 1
                    e.save()
                #db.session.commit()
                data = '{c1}개의 복사된 아이템을 삭제하였습니다.'.format(c1=len(entities))
            elif reqtype  == "no_item":
                from sqlalchemy import and_
                #c1 = db.session.query(ListModelItem).filter(and_(ListModelItem.obj_num == 0, ListModelItem.str_size == '0 Bytes')).delete()
                entities = db.session.query(ListModelItem).filter(and_(ListModelItem.obj_num == 0, ListModelItem.str_size == '0 Bytes')).all()
                for e in entities:
                    e.excluded = 1
                    e.save()
                #db.session.commit()
                data = '{c1}개의 불량 아이템을 삭제하였습니다.'.format(c1=len(entities))
            ret = {'ret':True, 'data':data}
            return ret
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return {'ret':False, 'data':''}


    @staticmethod
    def size_migration():
        try:
            from sqlalchemy import and_
            count = 0
            entity_list = db.session.query(ListModelItem).filter(and_(ListModelItem.byte_size == 0, ListModelItem.str_size != '-')).all()
            for e in entity_list:
                e.byte_size = LogicGSheet.get_byte_size(e.str_size)
                e.save()
                #logger.debug('%s:%s -> %d', e.title, e.str_size, e.byte_size)
                count += 1

            data = '{count}개 아이템의 사이즈를 변환하였습니다.'.format(count=count)
            ret = {'ret':True, 'data':data}
            return ret
        except Exception as e:
            logger.error('Exception %s', e)
            logger.error(traceback.format_exc())
            return {'ret':False, 'data':''}
