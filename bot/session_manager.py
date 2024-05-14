from common.expired_dict import ExpiredDict
from common.log import logger
from config import conf

import json
import os
from datetime import datetime


class Session(object):
    def __init__(self, session_id, system_prompt=None):
        self.session_id = session_id
        self.messages = []
        if system_prompt is None:
            self.system_prompt = conf().get("character_desc", "")
        else:
            self.system_prompt = system_prompt

    # 重置会话
    def reset(self):
        system_item = {"role": "system", "content": self.system_prompt}
        self.messages = [system_item]

    def set_system_prompt(self, system_prompt):
        self.system_prompt = system_prompt
        self.reset()

    def add_query(self, query):
        user_item = {"role": "user", "content": query}
        self.messages.append(user_item)

    def add_reply(self, reply):
        assistant_item = {"role": "assistant", "content": reply}
        self.messages.append(assistant_item)

    def discard_exceeding(self, max_tokens=None, cur_tokens=None):
        raise NotImplementedError

    def calc_tokens(self):
        raise NotImplementedError


class ConversationManager:
    def __init__(self, session_id, project_root_dir='.'):
        self.session_id = session_id
        # 确定项目的根目录
        self.project_root_dir = project_root_dir
        # 构建 JsonData 目录的完整路径
        self.data_dir = os.path.join(self.project_root_dir, 'JsonData')
        self.EnsureDataDirExists()
        self.MaybeCreateInitialFile()

    def EnsureDataDirExists(self):
        """确保数据目录存在"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

    def MaybeCreateInitialFile(self):
        """检查并创建初始文件"""
        data_path = self.GetDataPath()
        if not os.path.isfile(data_path):
            # 文件不存在，创建新文件并写入初始数据
            self.WriteData([])

    def GetDataPath(self):
        """获取数据文件路径"""
        return os.path.join(self.data_dir, f'session_{self.session_id}.json')

    def WriteData(self, data):
        """写入数据到文件"""
        with open(self.GetDataPath(), 'w') as file:
            json.dump(data, file, indent=4)

    def ReadData(self):
        """读取数据"""
        with open(self.GetDataPath(), 'r') as file:
            return json.load(file)

    def AppendMessage(self, message):
        """添加消息到会话"""
        data = self.ReadData()
        data.append(message)
        self.WriteData(data)

    def ResetConversation(self):
        """重置对话"""
        data = self.ReadData()
        reset_marker = {"reset": True, "timestamp": datetime.now().isoformat()}
        data.append(reset_marker)
        self.WriteData(data)

    def GetLastResetData(self):
        """获取最后一个重置后的数据"""
        data = self.ReadData()
        last_reset_index = None

        # 正向遍历以找到最后一个重置标记的索引
        for index, item in enumerate(data):
            if item.get("reset"):
                last_reset_index = index

        # 如果找到重置标记，返回该标记之后的所有内容
        if last_reset_index is not None:
            return data[last_reset_index + 1:] if last_reset_index + 1 < len(data) else []
        else:
            # 如果没有重置标记，返回所有内容
            return data


class SessionManager(object):
    def __init__(self, sessioncls, **session_args):
        if conf().get("expires_in_seconds"):
            sessions = ExpiredDict(conf().get("expires_in_seconds"))
        else:
            sessions = dict()
        self.sessions = sessions
        self.sessioncls = sessioncls
        self.session_args = session_args

    def build_session(self, session_id, system_prompt=None):
        """
        如果session_id不在sessions中，创建一个新的session并添加到sessions中
        如果system_prompt不会空，会更新session的system_prompt并重置session
        """
        if session_id is None:
            return self.sessioncls(session_id, system_prompt, **self.session_args)

        if session_id not in self.sessions:
            self.sessions[session_id] = self.sessioncls(session_id, system_prompt, **self.session_args)
        elif system_prompt is not None:  # 如果有新的system_prompt，更新并重置session
            self.sessions[session_id].set_system_prompt(system_prompt)
        session = self.sessions[session_id]
        return session

    def session_query(self, query, session_id):
        session = self.build_session(session_id)
        session.add_query(query)

        """
        other_user_id = session_id = receiver
        """


        # 数据持久化操作
        conversation_manager = ConversationManager(session_id)
        user_item_msg = {"role": "user", "content": query}
        conversation_manager.AppendMessage(user_item_msg)

        try:
            max_tokens = conf().get("conversation_max_tokens", 1000)
            total_tokens = session.discard_exceeding(max_tokens, None)
            logger.debug("prompt tokens used={}".format(total_tokens))
        except Exception as e:
            logger.warning("Exception when counting tokens precisely for prompt: {}".format(str(e)))
        return session

    def session_reply(self, reply, session_id, total_tokens=None):
        session = self.build_session(session_id)
        session.add_reply(reply)

        # 数据持久化操作
        conversation_manager = ConversationManager(session_id)
        assistant_item_msg = {"role": "assistant", "content": reply}
        conversation_manager.AppendMessage(assistant_item_msg)

        try:
            max_tokens = conf().get("conversation_max_tokens", 1000)
            tokens_cnt = session.discard_exceeding(max_tokens, total_tokens)
            logger.debug("raw total_tokens={}, savesession tokens={}".format(total_tokens, tokens_cnt))
        except Exception as e:
            logger.warning("Exception when counting tokens precisely for session: {}".format(str(e)))
        return session

    def clear_session(self, session_id):
        if session_id in self.sessions:
            del self.sessions[session_id]
            # 数据持久化操作
            conversation_manager = ConversationManager(session_id)
            conversation_manager.ResetConversation()

    def clear_all_session(self):
        self.sessions.clear()
