import os
import json
import datetime
import threading
import secrets

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    session,
    redirect,
    url_for,
)
import webview

# --------------------
# CONFIGURAÇÃO BÁSICA
# --------------------

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

DATA_FILE = "mesadas_data.json"

# Percentagens para distribuição de dívida/mesada
COFRE_DISTRIBUICAO = {
    "Diário": 0.50,
    "Sonhos": 0.20,
    "Poupança": 0.1875,
    "Doação": 0.0625,
}

DEFAULT_ALLOWANCE = {
    "Diário": 4.0,
    "Sonhos": 2.0,
    "Poupança": 1.5,
    "Doação": 0.5,
}


# --------------------
# FUNÇÕES AUXILIARES
# --------------------
def initialize_data_file():
    """Se o ficheiro não existir, cria com template."""
    if not os.path.exists(DATA_FILE):
        import shutil
        if os.path.exists('mesadas_data.template.json'):
            shutil.copy('mesadas_data.template.json', DATA_FILE)
        else:
            # Valores por defeito
            default_data = {
                "children": {},
                "users": {
                    "admin": {
                        "role": "gestor",
                        "password": "admin123",
                        "email": None,
                        "child_name": None
                    }
                }
            }
            with open(DATA_FILE, 'w') as f:
                json.dump(default_data, f, indent=2)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    # Garantir estrutura base
    if "users" not in data:
        data["users"] = {}
    if "children" not in data:
        # migração simples: se as crianças estavam na raiz, move-as
        children = {}
        for k, v in list(data.items()):
            if k not in ("users", "children"):
                children[k] = v
                del data[k]
        data["children"] = children

    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_next_saturday(base_date=None):
    if base_date is None:
        base_date = datetime.date.today()
    # sábado = 5 (segunda=0)
    days_ahead = (5 - base_date.weekday()) % 7
    if days_ahead == 0:
        # já é sábado, usamos este
        return base_date
    return base_date + datetime.timedelta(days=days_ahead)


def get_weekly_allowance_value(allowance_dict):
    return sum(allowance_dict.values())


def ensure_child_structure(child_name, data):
    """Garante que a criança tem todos os campos necessários."""
    children = data["children"]
    if child_name not in children:
        children[child_name] = {
            "allowance": DEFAULT_ALLOWANCE.copy(),
            "cofres": {k: 0.0 for k in DEFAULT_ALLOWANCE},
            "last_paid": str(get_next_saturday()),  # próxima data alvo
            "debt": 0.0,
            "last_payment_date": None,
            "transactions": [],
        }
    else:
        c = children[child_name]
        if "allowance" not in c:
            c["allowance"] = DEFAULT_ALLOWANCE.copy()
        if "cofres" not in c:
            c["cofres"] = {k: 0.0 for k in DEFAULT_ALLOWANCE}
        else:
            # garantir todos os cofres
            for k in DEFAULT_ALLOWANCE.keys():
                c["cofres"].setdefault(k, 0.0)
        if "last_paid" not in c:
            c["last_paid"] = str(get_next_saturday())
        if "debt" not in c:
            c["debt"] = 0.0
        if "last_payment_date" not in c:
            c["last_payment_date"] = None
        if "transactions" not in c:
            c["transactions"] = []


def add_transaction(child, tipo, cofre, descricao, montante):
    """
    Regista um movimento na lista de transactions da criança.
    tipo: 'Crédito' ou 'Débito'
    """
    now = datetime.datetime.now().isoformat()
    child.setdefault("transactions", [])
    child["transactions"].append(
        {
            "date": now,
            "type": tipo,
            "cofre": cofre,
            "description": descricao,
            "amount": float(montante),
        }
    )


def validate_and_update_debt_for_child(child):
    """
    Quando a aplicação arranca ou a criança é lida,
    garante que se passaram semanas desde a última data prevista de pagamento;
    se sim, acumula dívida.
    """
    today = datetime.date.today()
    last_paid_str = child.get("last_paid")
    if not last_paid_str:
        child["last_paid"] = str(get_next_saturday())
        return

    last_paid = datetime.date.fromisoformat(last_paid_str)

    # Se a próxima data prevista é no futuro em relação a hoje -> nada a fazer
    if last_paid >= today:
        return

    # Se já passou, calcular quantas semanas "em falta"
    delta_days = (today - last_paid).days
    weeks_missing = delta_days // 7
    if weeks_missing <= 0:
        return

    weekly_value = get_weekly_allowance_value(child["allowance"])
    child["debt"] += weekly_value * weeks_missing

    # Avança a last_paid em semanas_missing, mantendo o dia (sábado)
    child["last_paid"] = str(last_paid + datetime.timedelta(days=7 * weeks_missing))


def validate_all_children():
    """Percorre todas as crianças e aplica a validação de dívida/data."""
    data = load_data()
    for name in list(data["children"].keys()):
        ensure_child_structure(name, data)
        validate_and_update_debt_for_child(data["children"][name])
    save_data(data)


# --------------------
# AUTENTICAÇÃO
# --------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "username" in session:
            return redirect(url_for("index"))
        return render_template("login.html")

    # POST
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    data = load_data()
    users = data.get("users", {})
    user = users.get(username)

    if not user or user.get("password") != password:
        return render_template("login.html", error="Utilizador ou password inválidos")

    session["username"] = username
    session["role"] = user.get("role")
    if user.get("role") == "crianca":
        session["child_name"] = user.get("child_name")

    return redirect(url_for("index"))




@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/me", methods=["GET"])
def me():
    if "username" not in session:
        return jsonify({"authenticated": False}), 401

    info = {
        "authenticated": True,
        "username": session.get("username"),
        "role": session.get("role"),
    }
    if session.get("role") == "crianca":
        info["child_name"] = session.get("child_name")
    return jsonify(info)


def require_logged_in():
    if "username" not in session:
        return False
    return True


def require_gestor():
    return require_logged_in() and session.get("role") == "gestor"


# --------------------
# VISTAS PRINCIPAIS
# --------------------

@app.route("/")
def index():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("index.html")


# --------------------
# API: GESTÃO DE CRIANÇAS
# --------------------

@app.route("/api/children", methods=["GET"])
def get_children():
    if not require_logged_in():
        return jsonify({"error": "Não autenticado"}), 401

    data = load_data()
    return jsonify({"children": list(data["children"].keys())})


@app.route("/api/child/<name>", methods=["GET"])
def get_child(name):
    if not require_logged_in():
        return jsonify({"error": "Não autenticado"}), 401

    data = load_data()
    children = data["children"]

    if name not in children:
        return jsonify({"error": "Criança não encontrada"}), 404

    # Se for criança, só pode ver a própria
    if session.get("role") == "crianca":
        if session.get("child_name") != name:
            return jsonify({"error": "Não autorizado"}), 403

    child = children[name]
    ensure_child_structure(name, data)
    validate_and_update_debt_for_child(child)
    save_data(data)
    return jsonify(child)

@app.route("/api/child/add", methods=["POST"])
def add_child():
    if not require_gestor():
        return jsonify({"error": "Não autorizado"}), 403

    payload = request.get_json(force=True)
    name = payload.get("name", "").strip()
    role = payload.get("role", "crianca").strip()  # 'gestor' ou 'crianca'
    username = payload.get("username", "").strip()
    password = payload.get("password", "").strip()
    email = payload.get("email", "").strip()

    if not name:
        return jsonify({"error": "Nome não pode estar vazio"}), 400
    if not username:
        return jsonify({"error": "Utilizador não pode estar vazio"}), 400
    if not password:
        return jsonify({"error": "Password não pode estar vazia"}), 400

    data = load_data()
    children = data["children"]
    users = data.get("users", {})

    # Se for criança, adiciona também à lista de crianças
    if role == "crianca":
        if name in children:
            return jsonify({"error": "Criança já existe"}), 400
        children[name] = {
            "allowance": DEFAULT_ALLOWANCE.copy(),
            "cofres": {k: 0.0 for k in DEFAULT_ALLOWANCE},
            "last_paid": str(get_next_saturday()),
            "debt": 0.0,
            "last_payment_date": None,
            "transactions": [],
        }

    # Adiciona utilizador
    if username in users:
        return jsonify({"error": "Utilizador já existe"}), 400

    users[username] = {
        "role": role,
        "password": password,
        "email": email if email else None,
    }
    if role == "crianca":
        users[username]["child_name"] = name

    data["users"] = users
    save_data(data)
    return jsonify({"success": True})

@app.route("/api/users/request-password-reset", methods=["POST"])
def request_password_reset():
    """
    Utilizador esqueceu-se da password e faz um pedido de reset.
    Se tiver email, envia um link; caso contrário, avisa que deve contactar gestor.
    """
    payload = request.get_json(force=True)
    username = payload.get("username", "").strip()

    data = load_data()
    users = data.get("users", {})
    user = users.get(username)

    if not user:
        # Por segurança, não dizemos que o utilizador não existe
        return jsonify({
            "success": False,
            "message": "Se a conta existir, será enviado um email com instruções."
        })

    email = user.get("email")
    if not email:
        return jsonify({
            "success": False,
            "message": "Esta conta não tem email associado. Contacta o gestor para repor a password.",
            "no_email": True
        })

    # Aqui seria onde enviar email (com token de reset)
    # Por enquanto, apenas confirmamos que o utilizador tem email
    # Em produção, gerarias um token temporário e enviarias via email

    return jsonify({
        "success": True,
        "message": "Se o email estiver registado, receberás instruções para repor a password.",
        "email_sent": True
    })


@app.route("/api/child/remove", methods=["POST"])
def remove_child():
    if not require_gestor():
        return jsonify({"error": "Não autorizado"}), 403

    payload = request.get_json(force=True)
    name = payload.get("name", "").strip()

    data = load_data()
    children = data["children"]

    if name not in children:
        return jsonify({"error": "Criança não encontrada"}), 404

    del children[name]

    # Opcional: também podes querer apagar utilizadores do tipo criança com este child_name
    users = data.get("users", {})
    to_delete = []
    for uname, u in users.items():
        if u.get("role") == "crianca" and u.get("child_name") == name:
            to_delete.append(uname)
    for uname in to_delete:
        del users[uname]

    save_data(data)
    return jsonify({"success": True})


@app.route("/api/child/update-allowance", methods=["POST"])
def update_allowance():
    if not require_gestor():
        return jsonify({"error": "Não autorizado"}), 403

    payload = request.get_json(force=True)
    name = payload.get("name", "").strip()
    allowance = payload.get("allowance", {})

    data = load_data()
    children = data["children"]
    if name not in children:
        return jsonify({"error": "Criança não encontrada"}), 404

    new_allowance = {}
    for k, v in allowance.items():
        try:
            new_allowance[k] = float(v)
        except (TypeError, ValueError):
            return jsonify({"error": f"Valor inválido para {k}"}), 400

    children[name]["allowance"] = new_allowance
    save_data(data)
    return jsonify({"success": True})


# --------------------
# API: GASTOS, PAGAMENTOS, MOVIMENTOS
# --------------------

@app.route("/api/child/spend", methods=["POST"])
def spend():
    if not require_gestor():
        return jsonify({"error": "Não autorizado"}), 403

    payload = request.get_json(force=True)
    name = payload.get("name", "").strip()
    cofre = payload.get("cofre", "").strip()
    valor = float(payload.get("valor", 0))
    descricao = payload.get("descricao", "").strip() or "Gasto"

    data = load_data()
    children = data["children"]

    if name not in children:
        return jsonify({"error": "Criança não encontrada"}), 404

    child = children[name]
    ensure_child_structure(name, data)

    if cofre not in child["cofres"]:
        return jsonify({"error": "Cofre inválido"}), 400

    if valor <= 0:
        return jsonify({"error": "Valor inválido"}), 400

    if child["cofres"][cofre] < valor:
        return jsonify({"error": "Saldo insuficiente"}), 400

    child["cofres"][cofre] -= valor
    add_transaction(child, "Débito", cofre, descricao, valor)

    save_data(data)
    return jsonify({"success": True})


@app.route("/api/child/pay", methods=["POST"])
def pay_weekly():
    if not require_gestor():
        return jsonify({"error": "Não autorizado"}), 403

    payload = request.get_json(force=True)
    name = payload.get("name", "").strip()

    data = load_data()
    children = data["children"]

    if name not in children:
        return jsonify({"error": "Criança não encontrada"}), 404

    child = children[name]
    ensure_child_structure(name, data)

    # 1) Validar/atualizar dívida em falta (caso a data last_paid esteja no passado)
    validate_and_update_debt_for_child(child)

    # 2) Calcular valor semanal
    weekly_value = get_weekly_allowance_value(child["allowance"])

    # 3) Distribuir o valor semanal pelos cofres (mesada da semana atual)
    for cofre, percent in COFRE_DISTRIBUICAO.items():
        valor = weekly_value * percent
        child["cofres"][cofre] += valor
        add_transaction(child, "Crédito", cofre, "Mesada semanal", valor)

    # 4) Se existir dívida acumulada, pagar também agora
    if child["debt"] > 0:
        debt_to_pay = child["debt"]
        for cofre, percent in COFRE_DISTRIBUICAO.items():
            valor = debt_to_pay * percent
            child["cofres"][cofre] += valor
            add_transaction(child, "Crédito", cofre, "Pagamento de dívida", valor)
        child["debt"] = 0.0

    # 5) Atualizar datas
    today = datetime.date.today()
    child["last_payment_date"] = today.isoformat()
    # Avançar last_paid uma semana
    last_paid = datetime.date.fromisoformat(child["last_paid"])
    child["last_paid"] = str(last_paid + datetime.timedelta(days=7))

    save_data(data)
    return jsonify({"success": True})


@app.route("/api/child/<name>/transactions", methods=["GET"])
def get_transactions(name):
    if not require_logged_in():
        return jsonify({"error": "Não autenticado"}), 401

    data = load_data()
    children = data["children"]

    if name not in children:
        return jsonify({"error": "Criança não encontrada"}), 404

    # Se for criança, só pode ver a própria
    if session.get("role") == "crianca":
        if session.get("child_name") != name:
            return jsonify({"error": "Não autorizado"}), 403

    child = children[name]
    ensure_child_structure(name, data)
    transactions = child.get("transactions", [])
    return jsonify({"transactions": transactions})


# --------------------
# API: RESET PASSWORD (GESTOR)
# --------------------

@app.route("/api/users/reset-password", methods=["POST"])
def reset_password():
    if not require_gestor():
        return jsonify({"error": "Não autorizado"}), 403

    payload = request.get_json(force=True)
    username = payload.get("username", "").strip()
    new_password = payload.get("new_password", "").strip()

    if not username or not new_password:
        return jsonify({"error": "Utilizador e nova password são obrigatórios"}), 400

    data = load_data()
    users = data.get("users", {})

    if username not in users:
        return jsonify({"error": "Utilizador não encontrado"}), 404

    users[username]["password"] = new_password
    data["users"] = users
    save_data(data)

    return jsonify({"success": True})


# --------------------
# INICIALIZAÇÃO FLASK + PYWEBVIEW
# --------------------

def start_flask():
    # Ao arrancar, validar datas/dívidas de todas as crianças
    validate_all_children()
    app.run(debug=False, port=5000, use_reloader=False)


if __name__ == "__main__":
    initialize_data_file()
    threading.Thread(target=start_flask, daemon=True).start()
    webview.create_window(
#        "Gestão de Mesadas", "http://localhost:5000", width=1200, height=800
        "Gestão de Mesadas", "http://127.0.0.1:5000", width=1200, height=800
    )
    webview.start()
