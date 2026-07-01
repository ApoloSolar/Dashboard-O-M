#!/usr/bin/env python3
"""
Busca os dados do módulo Projeto (O&M) no Odoo via XML-RPC e grava docs/data.json.

As credenciais vêm de VARIÁVEIS DE AMBIENTE (GitHub Secrets) — nunca ficam no
código nem no arquivo publicado:
    ODOO_URL       ex.: https://apolo-solar2.odoo.com
    ODOO_DB        nome do banco
    ODOO_USERNAME  login (e-mail)
    ODOO_API_KEY   chave de API

Roda apenas com a biblioteca padrão do Python (sem pip install).
"""

import json
import os
import sys
import datetime
import xmlrpc.client

URL = (os.environ.get("ODOO_URL") or "").rstrip("/")
DB = os.environ.get("ODOO_DB") or ""
USERNAME = os.environ.get("ODOO_USERNAME") or ""
API_KEY = os.environ.get("ODOO_API_KEY") or ""

# Onde o dashboard espera encontrar os dados
SAIDA = os.path.join(os.path.dirname(__file__), "..", "docs", "data.json")


def url_base():
    base = URL
    if base.endswith("/odoo"):
        base = base[: -len("/odoo")]
    return base


def conectar():
    faltando = [k for k, v in {
        "ODOO_URL": URL, "ODOO_DB": DB,
        "ODOO_USERNAME": USERNAME, "ODOO_API_KEY": API_KEY,
    }.items() if not v]
    if faltando:
        sys.exit(f"[ERRO] Variáveis de ambiente ausentes: {', '.join(faltando)}")

    base = url_base()
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common")
    uid = common.authenticate(DB, USERNAME, API_KEY, {})
    if not uid:
        sys.exit("[ERRO] Falha na autenticação. Verifique DB, USERNAME e API_KEY.")
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object")
    return uid, models


def call(models, uid, modelo, metodo, args, kwargs=None):
    return models.execute_kw(DB, uid, API_KEY, modelo, metodo, args, kwargs or {})


def mapa_usuarios(models, uid):
    """id -> nome, para traduzir os responsáveis das tarefas."""
    users = call(models, uid, "res.users", "search_read", [[]],
                 {"fields": ["id", "name"]})
    return {u["id"]: u["name"] for u in users}


def rel_nome(valor):
    """many2one vem como [id, 'Nome'] -> 'Nome'."""
    if isinstance(valor, list) and len(valor) == 2:
        return valor[1]
    return None


def buscar_tarefas(models, uid, users):
    campos = ["id", "name", "project_id", "stage_id", "state",
              "user_ids", "priority", "date_deadline", "create_date"]
    total = call(models, uid, "project.task", "search_count", [[]])

    tarefas = []
    offset = 0
    while offset < total:
        lote = call(models, uid, "project.task", "search_read", [[]],
                    {"fields": campos, "limit": 200, "offset": offset, "order": "id"})
        for t in lote:
            resp_ids = t.get("user_ids") or []
            resp = " + ".join(users.get(i, f"ID {i}") for i in resp_ids) if resp_ids else "Sem responsável"
            tarefas.append({
                "id": t.get("id"),
                "name": t.get("name") or "",
                "project": rel_nome(t.get("project_id")) or "—",
                "stage": (f'{t["stage_id"][0]}: {t["stage_id"][1]}'
                          if isinstance(t.get("stage_id"), list) else "—"),
                "state": t.get("state") or "—",
                "resp": resp,
                "priority": int(t.get("priority") or 0),
                "deadline": (t["date_deadline"][:10] if t.get("date_deadline") else None),
                "created": (t["create_date"][:10] if t.get("create_date") else None),
            })
        offset += 200
    return tarefas


def main():
    uid, models = conectar()
    users = mapa_usuarios(models, uid)
    tarefas = buscar_tarefas(models, uid, users)

    saida = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "count": len(tarefas),
        "tasks": tarefas,
    }
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)

    print(f"OK: {len(tarefas)} tarefas gravadas em {os.path.relpath(SAIDA)}")


if __name__ == "__main__":
    main()
