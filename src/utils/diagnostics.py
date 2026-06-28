"""诊断工具

提供：
- log_exception_with_traceback(logger, exc, message, **context):
    统一的异常日志格式：warning + 完整 traceback + 业务上下文
- safe_call(func, *args, default=None, logger=None, op_name="", **context):
    安全调用某个函数，异常时打 warning+traceback 并返回 default
"""
import logging
import traceback
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def log_exception_with_traceback(
    logger: logging.Logger,
    exc: BaseException,
    message: str,
    level: int = logging.WARNING,
    **context: Any,
) -> None:
    """统一的异常日志：标题 + 完整 traceback + 业务上下文

    关键：必须用 traceback.format_exc() 而非 str(exc)，否则看不到堆栈。

    Args:
        logger: 日志对象
        exc: 异常实例
        message: 简短描述
        level: 日志级别，默认 WARNING
        **context: 业务上下文，会拼到日志末尾
    """
    tb_text = traceback.format_exc()
    ctx_text = ""
    if context:
        ctx_text = " | " + " ".join(
            f"{k}={v!r}" for k, v in context.items()
        )
    logger.log(
        level,
        f"{message}: {type(exc).__name__}: {exc}{ctx_text}\n{tb_text}",
    )


def safe_call(
    func: Callable[..., T],
    *args: Any,
    default: Any = None,
    logger: logging.Logger = None,
    op_name: str = "",
    log_level: int = logging.WARNING,
    **context: Any,
) -> Any:
    """安全调用函数，异常时打 warning+traceback 并返回 default

    用法：
        combos = safe_call(
            model.get_active_combos_count,
            logger=tag_logger, op_name="get_active_combos_count",
            hand_str=hand_str, state_id=id(state),
            default=0,
        )

    Args:
        func: 要调用的函数
        *args: 位置参数
        default: 异常时返回的默认值
        logger: 日志对象（None 时用 root logger）
        op_name: 操作名（用于日志定位）
        log_level: 异常时的日志级别
        **context: 业务上下文，会拼到日志末尾
    """
    lg = logger or logging.getLogger()
    try:
        return func(*args)
    except Exception as e:
        name = op_name or getattr(func, "__name__", str(func))
        log_exception_with_traceback(
            lg, e,
            f"[safe_call] {name} 异常",
            level=log_level,
            **context,
        )
        return default
