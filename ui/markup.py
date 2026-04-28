from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Iterable, Mapping


TEMPLATES_DIR = Path(__file__).with_name("templates")


def _e(value: object) -> str:
    return escape(str(value))


@lru_cache(maxsize=None)
def _template(template_name: str) -> str:
    return (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")


def _format_markup(markup: str, *, raw: dict[str, object] | None = None, **values: object) -> str:
    escaped_values = {key: _e(value) for key, value in values.items()}
    if raw:
        escaped_values.update({key: str(value) for key, value in raw.items()})
    return markup.format(**escaped_values)


def _render(template_name: str, *, raw: dict[str, object] | None = None, **values: object) -> str:
    return _format_markup(_template(template_name), raw=raw, **values)


def spacer_html(height: int) -> str:
    return _format_markup('<div style="height:{height}px"></div>', height=height)


def sidebar_header_html() -> str:
    return _template("sidebar_header.html")


def section_label_html(
    label: str,
    *,
    color: str = "#555",
    margin_bottom: int = 12,
    font_size: int = 11,
) -> str:
    return _format_markup(
        '<div class="section-label" style="font-size:{font_size}px;font-weight:600;letter-spacing:.9px;text-transform:uppercase;color:{color};margin-bottom:{margin_bottom}px;line-height:1.4;padding-bottom:2px">{label}</div>',
        label=label,
        color=color,
        margin_bottom=margin_bottom,
        font_size=font_size,
    )


def empty_state_html(message: str, *, margin_top: int = 8, color: str = "#555") -> str:
    return _format_markup(
        '<p style="font-size:12px;color:{color};margin-top:{margin_top}px">{message}</p>',
        message=message,
        color=color,
        margin_top=margin_top,
    )


def error_html(message: str, *, margin_top: int = 8) -> str:
    return empty_state_html(message, margin_top=margin_top, color="#E8192C")


def weather_card_html(weather: Mapping[str, object]) -> str:
    current = weather.get("current")
    current_map: Mapping[str, object] = current if isinstance(current, Mapping) else {}
    forecast = weather.get("forecast")
    forecast_items = [day for day in forecast if isinstance(day, Mapping)] if isinstance(forecast, list) else []

    forecast_html = "".join(
        _format_markup(
            '<div style="font-size:11px;color:#555;margin-top:4px">{date}: <span style="color:#999">{min_c}&ndash;{max_c}&deg;C</span> &middot; {description}</div>',
            date=day["date"],
            min_c=day["min_c"],
            max_c=day["max_c"],
            description=day["description"],
        )
        for day in forecast_items
    )

    return _render(
        "weather_card.html",
        raw={"forecast_html": forecast_html},
        city=weather["city"],
        description=current_map["description"],
        temp_c=current_map["temp_c"],
        feels_like_c=current_map["feels_like_c"],
        humidity=current_map["humidity"],
        wind_kmph=current_map["wind_kmph"],
    )


def sidebar_footer_html() -> str:
    return (
        '<div class="sidebar-footer">'
        '<div class="footer-row">'
        '<span class="footer-brand">TRIPPLANNER</span>'
        '<span class="footer-version">v 1.0</span>'
        '</div>'
        '</div>'
    )


def hero_html() -> str:
    return _template("hero.html")


def popular_destinations_html(destinations: Iterable[str]) -> str:
    pills_html = "".join(
        _format_markup(
            '<span style="background:#131313;border:1px solid #262626;border-radius:20px;padding:6px 14px;font-size:12.5px;color:#bbb;display:inline-flex;align-items:center">{name}</span>',
            name=name,
        )
        for name in destinations
    )
    return _format_markup(
        '<div style="margin-top:44px">'
        '<div style="font-size:11px;font-weight:600;letter-spacing:.9px;text-transform:uppercase;color:#555;margin-bottom:14px">Popular destinations</div>'
        '<div style="display:flex;flex-wrap:wrap;gap:7px">{pills_html}</div>'
        '</div>',
        raw={"pills_html": pills_html},
    )


def source_chunk_html(chunk: Mapping[str, object], index: int) -> str:
    return _render(
        "source_chunk.html",
        index=index,
        source=chunk["source"],
        score=chunk["score"],
        text=chunk["text"],
    )


def source_expander_label(count: int) -> str:
    suffix = "s" if count != 1 else ""
    return f"Sources used ({count} source{suffix})"