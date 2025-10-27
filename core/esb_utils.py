"""
ESB 工具类 - 用于处理 ESB 请求和响应的包裹
"""
from datetime import date
from enum import Enum
import threading
import time
from typing import Dict, Any

APP_NAME = "AIMP"


# 线程安全的计数器
class Counter:
    __slots__ = ('_lock', '_value', '_last_ms')

    def __init__(self):
        self._lock = threading.Lock()
        self._value = 0
        self._last_ms = 0

    def get_next(self):
        current_ms = int(time.time() * 1000)
        with self._lock:
            # 如果进入新毫秒则重置计数器
            if current_ms != self._last_ms:
                self._value = 0
                self._last_ms = current_ms

            self._value += 1
            # 确保计数器在16位内 (0-999999)
            seq_val = self._value % 1_000_000
            return current_ms, seq_val


# 全局线程安全计数器实例
counter = Counter()


class EsbRespStatus(Enum):
    """ESB 响应状态枚举"""
    SUCCESS = ("S", "成功")
    FAIL = ("F", "失败")
    UNKNOWN = ("U", "未知")
    UN_AUTH = ("A", "需要授权")

    def __init__(self, code: str, msg: str):
        self._code = code
        self._msg = msg

    @property
    def code(self) -> str:
        """获取状态码"""
        return self._code

    @property
    def msg(self) -> str:
        """获取状态描述"""
        return self._msg

    def __str__(self):
        return f"{self.name}({self.code}: {self.msg})"

    def __repr__(self):
        return self.__str__()


class RspInfoDto:
    """
    ESB 返回头对象
    对应 Java 中的 com.ksrcb.daas.dsbs.domain.esb.common.rspInfoDto
    """

    def __init__(self):
        # 初始化所有字段为 None
        self.rsp_info = {
            "IttrDt": "",
            "IttrStmInd": "",
            "IttrChlInd": "",
            "GloSeqNum": "",
            "I18nInd": "",
            "ReqStmInd": "",
            "SvcNo": "",
            "ScnNo": "",
            "SvcVerNo": "",
            "ScnVerNo": "",
            "ReqStmDt": "",
            "ReqStmTm": "",
            "ReqSeqNum": "",
            "LegOrgId": "",
            "MAC": None,
            "BckInd": None,
            "BckId": None,
            "SvcStmInd": "",
            "SvcStmTxnDt": "",
            "SvcStmRespSeqNum": "",
            "TechFlw": None,
            "RespSt": "",
            "RespInfo": "",
            "RespInfoDsc": ""
        }

    @staticmethod
    def generate_response_seq():
        """
        生成安全的响应序列号（线程安全）

        格式: R + 4位系统编码 + 8位日期(yyyyMMdd) + 3位预留码(000) + 16位随机码
        16位随机码 = 当前毫秒数(13位) + 3位随机数 (总长16位)

        参数:
        system_code: 4位系统标识码，默认"KSRB"(昆山农商行)

        返回:
        str: 27位响应序列号
        """
        # 获取当前时间
        now = time.localtime()

        # 生成日期部分
        date_part = time.strftime("%Y%m%d", now)

        # 获取可并发的原子序列值
        timestamp_ms, seq_val = counter.get_next()

        # 处理时间戳：取后10位，不足10位前补0（实际时间戳有13位，取模10^10）
        timestamp_part = str(timestamp_ms % 10 ** 10).zfill(10)[-10:]
        # 序列值部分：6位，不足6位补0
        seq_part = str(seq_val).zfill(6)[-6:]

        # 组合16位
        unique_code = timestamp_part + seq_part

        return f"R{APP_NAME}{date_part}000{unique_code}"

    def build_rsp_info_dto(self, request: Dict[str, Any], resp_st: EsbRespStatus, resp_info_code: str, desc: str):
        """
        构建响应信息 DTO，逻辑与 Java 代码完全一致
        :param request: ESB 请求对象（包含 ReqInfo）
        :param resp_st: 响应状态枚举
        :param resp_info_code: 响应信息码
        :param desc: 响应描述
        :return: self (支持链式调用)
        """
        req_info = request.get("ReqInfo", {})

        # 设置响应信息
        self.rsp_info["IttrDt"] = req_info.get("IttrDt", "")
        self.rsp_info["IttrStmInd"] = req_info.get("IttrStmInd", "")
        self.rsp_info["IttrChlInd"] = req_info.get("IttrChlInd", "")
        self.rsp_info["GloSeqNum"] = req_info.get("GloSeqNum", "")
        self.rsp_info["I18nInd"] = req_info.get("I18nInd", "")
        self.rsp_info["ReqStmInd"] = req_info.get("ReqStmInd", "")
        self.rsp_info["ReqStmDt"] = req_info.get("ReqStmDt", "")
        self.rsp_info["ReqStmTm"] = req_info.get("ReqStmTm", "")
        self.rsp_info["SvcNo"] = req_info.get("SvcNo", "")
        self.rsp_info["ScnNo"] = req_info.get("ScnNo", "")
        self.rsp_info["SvcVerNo"] = req_info.get("SvcVerNo", "")
        self.rsp_info["ScnVerNo"] = req_info.get("ScnVerNo", "")
        self.rsp_info["ReqSeqNum"] = req_info.get("ReqSeqNum", "")
        self.rsp_info["LegOrgId"] = req_info.get("LegOrgId", "")
        self.rsp_info["SvcStmInd"] = APP_NAME
        self.rsp_info["SvcStmTxnDt"] = date.today().isoformat()  # LocalDate.now().toString() -> ISO 格式
        self.rsp_info["SvcStmRespSeqNum"] = self.generate_response_seq()
        self.rsp_info["RespSt"] = resp_st.code
        self.rsp_info["RespInfo"] = APP_NAME + resp_info_code
        self.rsp_info["RespInfoDsc"] = desc

        return self

    def to_dict(self):
        """转换为字典"""
        return self.rsp_info


class EsbWrapper:
    """ESB 请求和响应包裹器"""

    @staticmethod
    def unwrap_request(esb_request: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 ESB 请求中解包业务数据

        Args:
            esb_request: ESB 格式的请求，包含 ReqInfo 和 Request
                        Request 中还包含 input 字段

        Returns:
            Dict: 业务请求数据（Request.input 部分）
        """
        if "Request" not in esb_request:
            raise ValueError("Invalid ESB request: missing 'Request' field")

        request_data = esb_request["Request"]

        # 检查是否有 input 字段
        if "input" not in request_data:
            raise ValueError("Invalid ESB request: missing 'input' field in Request")

        return request_data["input"]

    @staticmethod
    def wrap_response(
        esb_request: Dict[str, Any],
        business_data: Dict[str, Any],
        resp_st: EsbRespStatus = EsbRespStatus.SUCCESS,
        resp_info_code: str = "0000",
        desc: str = "成功"
    ) -> Dict[str, Any]:
        """
        将业务响应包裹为 ESB 格式

        Args:
            esb_request: 原始 ESB 请求（用于构造响应头）
            business_data: 业务响应数据
            resp_st: 响应状态
            resp_info_code: 响应信息码
            desc: 响应描述

        Returns:
            Dict: ESB 格式的响应
        """
        # 创建响应头
        rsp_info_dto = RspInfoDto()
        rsp_info_dto.build_rsp_info_dto(esb_request, resp_st, resp_info_code, desc)

        # 组装完整响应，业务数据包裹在 output 字段中
        return {
            "RspInfo": rsp_info_dto.to_dict(),
            "Response": {
                "output": business_data
            }
        }

    @staticmethod
    def wrap_error_response(
        esb_request: Dict[str, Any],
        error_message: str,
        error_code: str = "9999"
    ) -> Dict[str, Any]:
        """
        将错误信息包裹为 ESB 格式

        Args:
            esb_request: 原始 ESB 请求
            error_message: 错误信息
            error_code: 错误码

        Returns:
            Dict: ESB 格式的错误响应
        """
        return EsbWrapper.wrap_response(
            esb_request=esb_request,
            business_data={"error": True, "message": error_message},
            resp_st=EsbRespStatus.FAIL,
            resp_info_code=error_code,
            desc=error_message
        )
