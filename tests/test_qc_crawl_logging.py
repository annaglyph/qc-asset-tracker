import logging

import qc_crawl


def test_ignore_empty_message_filter_filters_empty_and_whitespace():
    flt = qc_crawl.IgnoreEmptyMessageFilter()

    empty = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    )
    spaces = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=0,
        msg="   ",
        args=(),
        exc_info=None,
    )
    normal = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=0,
        msg="hello",
        args=(),
        exc_info=None,
    )

    assert flt.filter(empty) is False
    assert flt.filter(spaces) is False
    assert flt.filter(normal) is True


def test_configure_logging_quiet_raises_effective_level():
    # Start from a clean config
    qc_crawl.configure_logging(level_name="DEBUG", quiet=True, json_logs=False)
    root = logging.getLogger()
    # Quiet mode should never be more verbose than WARNING
    assert root.level >= logging.WARNING


def test_configure_logging_uses_json_formatter_when_requested():
    qc_crawl.configure_logging(level_name="INFO", quiet=False, json_logs=True)
    root = logging.getLogger()

    assert any(isinstance(h.formatter, qc_crawl.JsonFormatter) for h in root.handlers)


def test_configure_logging_uses_colour_formatter_for_text_logs():
    qc_crawl.configure_logging(level_name="INFO", quiet=False, json_logs=False)
    root = logging.getLogger()

    assert any(isinstance(h.formatter, qc_crawl.ColourFormatter) for h in root.handlers)


def test_configure_logging_attaches_ignore_empty_message_filter():
    qc_crawl.configure_logging(level_name="INFO", quiet=False, json_logs=False)
    root = logging.getLogger()

    assert any(
        any(isinstance(f, qc_crawl.IgnoreEmptyMessageFilter) for f in h.filters)
        for h in root.handlers
    )
