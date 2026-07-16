#!/usr/bin/env python3
"""
Busca os dados do módulo Projeto (O&M) no Odoo via XML-RPC e grava docs/data.json.

Campos trazidos, além dos básicos:
  - USINA        -> tag_ids (resolvido para os nomes das tags/usinas)
  - SEVERIDADE   -> x_studio_severidade
  - TIPO         -> x_studio_tipo_de_manutencao
  - TEMPO ABERTO -> dias entre a criação e a entrada em FINALIZADO
                    (date_last_stage_update - create_date, só p/ finalizadas)

Credenciais vêm de variáveis de ambiente (GitHub Secrets):
    ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY

Roda só com a biblioteca padrão do Python.
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

SAIDA = os.path.join(os.path.dirname(__file__), "..", "docs", "data.json")

# Nomes técnicos dos campos customizados (descobertos na exportação).
CAMPO_SEVERIDADE = "x_studio_severidade"
CAMPO_TIPO = "x_studio_tipo_de_manutencao"


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


def mapa(models, uid, modelo):
    """id -> nome para um modelo (usuários, tags...).

    Usa active_test=False para INCLUIR registros arquivados/desativados.
    Sem isso, um usuário desligado (arquivado) some da busca e as tarefas
    dele apareceriam como 'ID 6' em vez do nome.
    """
    regs = call(models, uid, modelo, "search_read", [[]],
                {"fields": ["id", "name"], "context": {"active_test": False}})
    return {r["id"]: r["name"] for r in regs}


def resolver_faltantes(models, uid, modelo, mapa_atual, ids_usados):
    """Busca direto no Odoo qualquer id que não esteja no mapa (rede de segurança)."""
    faltando = sorted({i for i in ids_usados if i not in mapa_atual})
    if not faltando:
        return
    try:
        regs = call(models, uid, modelo, "read", [faltando],
                    {"fields": ["id", "name"], "context": {"active_test": False}})
        for r in regs:
            mapa_atual[r["id"]] = r["name"]
        print(f"[INFO] {modelo}: resolvidos {len(regs)} id(s) extra: {faltando}")
    except Exception as e:
        print(f"[AVISO] Não consegui resolver ids {faltando} em {modelo}: {e}")


def detectar_campos(models, uid):
    """Confere quais campos customizados existem e monta mapas de seleção."""
    meta = call(models, uid, "project.task", "fields_get", [],
                {"attributes": ["type", "selection", "string"]})
    campos = {}
    for chave, alvo in (("severidade", CAMPO_SEVERIDADE), ("tipo", CAMPO_TIPO)):
        if alvo in meta:
            campos[chave] = alvo
        else:
            # fallback: procura por aproximação no nome
            termo = "sever" if chave == "severidade" else "tipo"
            achado = next((f for f in meta if f.startswith("x_studio_") and termo in f.lower()
                           and (chave != "tipo" or "manuten" in f.lower())), None)
            campos[chave] = achado
            print(f"[AVISO] Campo '{alvo}' não encontrado; usando '{achado}'.")
    # mapas de seleção (chave -> rótulo), quando for campo selection
    selmaps = {}
    for chave, nome in campos.items():
        if nome and meta.get(nome, {}).get("type") == "selection":
            selmaps[chave] = {str(k): v for k, v in (meta[nome].get("selection") or [])}
    print(f"[INFO] Campos usados -> severidade: {campos['severidade']}, tipo: {campos['tipo']}")
    return campos, selmaps


def parse_dt(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def rel_nome(v):
    return v[1] if isinstance(v, list) and len(v) == 2 else None


def buscar_tarefas(models, uid, users, tags, campos, selmaps):
    base_fields = ["id", "name", "project_id", "stage_id", "state", "user_ids",
                   "priority", "date_deadline", "create_date",
                   "date_last_stage_update", "tag_ids", "parent_id"]
    extra = [c for c in (campos["severidade"], campos["tipo"]) if c]
    fields = base_fields + extra

    # Exclui subtarefas (parent_id preenchido) e a tarefa de ID 1, já na busca.
    dominio = [["parent_id", "=", False], ["id", "!=", 1]]

    total = call(models, uid, "project.task", "search_count", [dominio])
    tarefas, offset = [], 0
    usados_users, usados_tags = set(), set()
    while offset < total:
        lote = call(models, uid, "project.task", "search_read", [dominio],
                    {"fields": fields, "limit": 200, "offset": offset, "order": "id"})
        for t in lote:
            # responsáveis / usinas: guardamos os ids e resolvemos os nomes no fim,
            # depois de buscar eventuais ids ausentes (ex.: usuário arquivado).
            rids = t.get("user_ids") or []
            tids = t.get("tag_ids") or []
            usados_users.update(rids)
            usados_tags.update(tids)
            # severidade / tipo
            def valor(chave):
                nome = campos.get(chave)
                if not nome:
                    return None
                v = t.get(nome)
                if not v:
                    return None
                if isinstance(v, list):        # se vier como [id, label]
                    return v[1]
                v = str(v)
                return selmaps.get(chave, {}).get(v, v)
            severidade = valor("severidade") or "—"
            tipo = valor("tipo") or "—"
            # tempo de conclusão (só finalizadas)
            stage_nome = t["stage_id"][1] if isinstance(t.get("stage_id"), list) else ""
            finalizada = "FINALIZ" in (stage_nome or "").upper()
            lead = None
            dc, df = parse_dt(t.get("create_date")), parse_dt(t.get("date_last_stage_update"))
            if finalizada and dc and df and df >= dc:
                lead = round((df - dc).total_seconds() / 86400, 1)

            tarefas.append({
                "id": t.get("id"),
                "name": t.get("name") or "",
                "project": rel_nome(t.get("project_id")) or "—",
                "stage": (f'{t["stage_id"][0]}: {t["stage_id"][1]}'
                          if isinstance(t.get("stage_id"), list) else "—"),
                "state": t.get("state") or "—",
                "_rids": rids,
                "_tids": tids,
                "severidade": severidade,
                "tipo": tipo,
                "priority": int(t.get("priority") or 0),
                "deadline": (t["date_deadline"][:10] if t.get("date_deadline") else None),
                "created": (t["create_date"][:10] if t.get("create_date") else None),
                "created_dt": t.get("create_date") or None,
                "closed": (t["date_last_stage_update"][:10] if finalizada and t.get("date_last_stage_update") else None),
                "closed_dt": (t.get("date_last_stage_update") if finalizada and t.get("date_last_stage_update") else None),
                "stage_since": t.get("date_last_stage_update") or None,
                "lead_days": lead,
            })
        offset += 200

    # Rede de segurança: busca direto os ids que não vieram no mapa
    # (ex.: usuário desligado/arquivado, tag arquivada).
    resolver_faltantes(models, uid, "res.users", users, usados_users)
    resolver_faltantes(models, uid, "project.tags", tags, usados_tags)

    # Agora monta os nomes com o mapa já completo.
    for t in tarefas:
        rids = t.pop("_rids")
        tids = t.pop("_tids")
        t["resp"] = " + ".join(users.get(i, f"ID {i}") for i in rids) if rids else "Sem responsável"
        t["usinas"] = [tags.get(i, f"Tag {i}") for i in tids]

    faltou = sorted({i for i in usados_users if i not in users})
    if faltou:
        print(f"[AVISO] Usuários ainda sem nome (aparecerão como 'ID x'): {faltou}")
    return tarefas


def main():
    uid, models = conectar()
    users = mapa(models, uid, "res.users")
    tags = mapa(models, uid, "project.tags")
    campos, selmaps = detectar_campos(models, uid)
    tarefas = buscar_tarefas(models, uid, users, tags, campos, selmaps)

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
