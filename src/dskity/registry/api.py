from __future__ import annotations

import datetime as dt
import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from dskity.config.loader import load_config
from dskity.registry.service_registry import ServiceRegistry

router = APIRouter(prefix="/_core", tags=["core-registry"])


def _registry(request: Request) -> ServiceRegistry | None:
    store = getattr(request.app.state, "registry_store", None)
    if store is None:
        return None
    return ServiceRegistry(store=store)


@router.get("/services", response_class=HTMLResponse)
def services_html(request: Request) -> HTMLResponse:
    reg = _registry(request)
    if reg is None:
        return HTMLResponse(
            "<html><body><h1>Service discovery</h1>\
                                        <p>registry desabilitado (common.registry.enabled=false)</p>\
                        </body></html>",
            status_code=200,
        )

    now = dt.datetime.now(dt.timezone.utc)
    rows = reg.aggregate_services(now=int(now.timestamp()))

    def fmt_ts(ts: int | None) -> str:
        if not ts:
            return "-"
        return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat()

    def fmt_age(age: int | None) -> str:
        if age is None:
            return "-"
        return f"{age}s"

    trs: list[str] = []
    for row in rows:
        service = html.escape(str(row.get("service", "")))
        count = int(row.get("instances_count") or 0)
        last_hb = row.get("last_heartbeat")
        age = row.get("last_heartbeat_age_seconds")
        link = f"/_core/services/{service}.json"

        trs.append(
            "<tr>"
            f"<td>{service}</td>"
            f"<td style='text-align:right'>{count}</td>"
            f"<td>{html.escape(fmt_ts(last_hb))}</td>"
            f"<td>{html.escape(fmt_age(age))}</td>"
            f"<td><a href='{link}'>instâncias (json)</a></td>"
            "</tr>"
        )

    body = "".join(trs) if trs else "<tr><td colspan='5'>Nenhum serviço registrado ainda</td></tr>"

    page = f"""<!doctype html>
<html lang='pt-br'>
    <head>
        <meta charset='utf-8' />
        <meta name='viewport' content='width=device-width, initial-scale=1' />
        <title>Service discovery</title>
    </head>
    <body style='font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px;'>
        <h1 style='margin: 0 0 8px 0;'>Service discovery</h1>
        <div style='margin: 0 0 16px 0; color: #444;'>
            Atualizado em: {html.escape(now.isoformat())} (UTC)
        </div>
        <table border='1' cellpadding='8' cellspacing='0' style='border-collapse: collapse; min-width: 720px;'>
            <thead style='background: #f5f5f5;'>
                <tr>
                    <th align='left'>Serviço</th>
                    <th align='right'>Instâncias</th>
                    <th align='left'>Último heartbeat (UTC)</th>
                    <th align='left'>Idade</th>
                    <th align='left'>Detalhe</th>
                </tr>
            </thead>
            <tbody>
                {body}
            </tbody>
        </table>
        <div style='margin-top: 16px; color: #666;'>
            API JSON: <a href='/_core/services.json'>/_core/services.json</a>
        </div>
    </body>
</html>"""

    return HTMLResponse(page, status_code=200)


@router.get("/services.json")
def list_services_json(request: Request) -> dict:
    reg = _registry(request)
    if reg is None:
        return {"enabled": False, "services": []}
    return {"enabled": True, "services": reg.list_services()}


@router.get("/services/{service}.json")
def list_instances_json(service: str, request: Request) -> dict:
    reg = _registry(request)
    if reg is None:
        return {"enabled": False, "service": service, "instances": []}
    return {"enabled": True, "service": service, "instances": reg.list_instances(service)}


@router.get("/config", response_class=HTMLResponse)
def config_html(request: Request) -> HTMLResponse:
    """Exibe configuração atual da aplicação (incluindo credenciais)."""
    # Tenta pegar config do app.state, senão carrega novamente
    config = getattr(request.app.state, "config", None)
    if config is None:
        config = load_config()

    # Converte para dict recursivamente
    config_dict = config.model_dump(exclude_none=True)

    def render_value(v) -> str:
        """Renderiza valor com destaque para credenciais."""
        if v is None:
            return "<em style='color: #999;'>null</em>"
        if isinstance(v, bool):
            return f"<strong style='color: {'#0a0' if v else '#c00'};'>{str(v).lower()}</strong>"
        if isinstance(v, (int, float)):
            return f"<span style='color: #00a;'>{v}</span>"
        if isinstance(v, str):
            # Destaca possíveis credenciais
            if any(word in v.lower() for word in ["password", "token", "secret"]) or "://" in v and "@" in v:
                return f"<span style='color: #d60; background: #ffc;'>{html.escape(v)}</span>"
            return html.escape(v)
        return html.escape(str(v))

    def render_dict(d: dict, level: int = 0) -> str:
        """Renderiza dicionário como HTML aninhado."""
        if not d:
            return "<div style='color: #999;'>{}</div>"

        indent = 20 * level
        items = []
        for key, value in sorted(d.items()):
            key_html = f"<strong>{html.escape(key)}:</strong>"

            if isinstance(value, dict):
                value_html = render_dict(value, level + 1)
                items.append(f"<div style='margin-left: {indent}px;'>{key_html}{value_html}</div>")
            else:
                value_html = render_value(value)
                items.append(f"<div style='margin-left: {indent}px;'>{key_html} {value_html}</div>")

        return "".join(items)

    now = dt.datetime.now(dt.timezone.utc)
    body = render_dict(config_dict)

    page = f"""<!doctype html>
<html lang='pt-br'>
	<head>
		<meta charset='utf-8' />
		<meta name='viewport' content='width=device-width, initial-scale=1' />
		<title>Configuração da Aplicação</title>
	</head>
	<body style='font-family: ui-monospace, Menlo, Monaco, Consolas, monospace; margin: 24px; font-size: 13px;'>
		<h1 style='font-family: ui-sans-serif, system-ui, -apple-system; margin: 0 0 8px 0;'>
                        Configuração da Aplicação
                </h1>
		<div style='margin: 0 0 16px 0; color: #666; font-family: ui-sans-serif, system-ui;'>
			Carregado em: {html.escape(now.isoformat())} (UTC)
		</div>
		<div style='padding: 16px; background: #f8f8f8; border: 1px solid #ddd; border-radius: 4px; line-height: 1.6;'>
			{body}
		</div>
		<div style='margin-top: 16px; color: #666; font-family: ui-sans-serif, system-ui;'>
			API JSON: <a href='/_core/config.json'>/_core/config.json</a> | 
			<a href='/_core/services'>← Voltar para Services</a>
		</div>
		<div style='margin-top: 8px; padding: 12px; 
                        background: #fff3cd; border: 1px solid #ffc107; 
                        border-radius: 4px; color: #856404; font-family: ui-sans-serif, system-ui;'>
			⚠️ <strong>Aviso:</strong> Esta página exibe credenciais e informações sensíveis. Não exponha em produção.
		</div>
	</body>
</html>"""

    return HTMLResponse(page, status_code=200)


@router.get("/config.json")
def config_json(request: Request) -> dict:
    """Retorna configuração atual em formato JSON."""
    config = getattr(request.app.state, "config", None)
    if config is None:
        config = load_config()

    return config.model_dump(exclude_none=True)
