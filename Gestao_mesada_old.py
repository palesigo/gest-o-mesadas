# Estrutura:
# Projeto/
# â”œâ”€â”€ app_pywebview.py (este ficheiro)
# â””â”€â”€ templates/
#     â””â”€â”€ index.html

from flask import Flask, render_template, request, jsonify
import threading
import webview
import json
import datetime
import os

app = Flask(__name__)

DATA_FILE = "mesadas_data.json"
DEFAULT_ALLOWANCE = {
    "Diário": 4.0,
    "Sonhos": 2.0,
    "Poupança": 1.5,
    "Doação": 0.5
}

# ProporÃ§Ã£o de distribuiÃ§Ã£o do valor em falta pagar
DEBT_DISTRIBUTION = {
    "Diário": 0.50,      # 50%
    "Sonhos": 0.20,      # 20%
    "Poupança": 0.1875,  # 18.75%
    "Doação": 0.0625     # 6.25%
}

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_next_saturday():
    """Calcula a próxima data de sábado"""
    today = datetime.date.today()
    days_until_sat = (5 - today.weekday()) % 7
    if days_until_sat == 0:
        days_until_sat = 7
    return today + datetime.timedelta(days=days_until_sat)

def add_transaction(child_data, tipo, cofre, descricao, montante):
    """Adiciona um movimento ao histórico"""
    if 'transactions' not in child_data:
        child_data['transactions'] = []
    
    transaction = {
        'date': datetime.datetime.now().isoformat(),
        'type': tipo,  # 'CrÃ©dito' ou 'DÃ©bito'
        'cofre': cofre,
        'description': descricao,
        'amount': montante
    }
    child_data['transactions'].append(transaction)

def validate_and_update_dates():
    """
    Valida e atualiza as datas de próximo pagamento e dívidas
    Executado quando a aplicação inicia
    """
    data = load_data()
    today = datetime.date.today()
    next_saturday = get_next_saturday()
    
    for child_name, child_data in data.items():
        last_paid = datetime.date.fromisoformat(child_data['last_paid'])
        
        # Se a data de prÃ³ximo pagamento Ã© igual Ã  atual, nÃ£o fazer nada
        if last_paid == next_saturday:
            continue
        
        # Se a data de prÃ³ximo pagamento Ã© superior Ã  atual
        # (ou seja, jÃ¡ passou), adicionar a mesada Ã  dÃ­vida
        if last_paid < next_saturday:
            # Calcular quantas semanas se passaram
            weeks_passed = (next_saturday - last_paid).days // 7
            
            # Adicionar Ã  dÃ­vida o valor correspondente ao nÃºmero de semanas
            for _ in range(weeks_passed):
                for cofre, valor in child_data["allowance"].items():
                    child_data['debt'] += valor
            
            # Atualizar a data para o prÃ³ximo sÃ¡bado
            child_data['last_paid'] = next_saturday.isoformat()
    
    save_data(data)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/validate-dates', methods=['POST'])
def validate_dates():
    """Endpoint para validar e atualizar datas (chamado na inicializaÃ§Ã£o)"""
    validate_and_update_dates()
    return jsonify({"success": True})

@app.route('/api/children', methods=['GET'])
def get_children():
    data = load_data()
    return jsonify({"children": list(data.keys())})

@app.route('/api/child/<name>', methods=['GET'])
def get_child(name):
    data = load_data()
    if name in data:
        return jsonify(data[name])
    return jsonify({"error": "Criança não encontrada"}), 404

@app.route('/api/child/<name>/transactions', methods=['GET'])
def get_transactions(name):
    """Retorna o histórico de movimentos"""
    data = load_data()
    if name in data:
        transactions = data[name].get('transactions', [])
        return jsonify({"transactions": transactions})
    return jsonify({"error": "Criança não encontrada"}), 404

@app.route('/api/child/add', methods=['POST'])
def add_child():
    name = request.json.get('name', '').strip()
    if not name:
        return jsonify({"error": "Nome não pode estar vazio"}), 400
    data = load_data()
    if name in data:
        return jsonify({"error": "Criança já existe"}), 400
    
    # Primeira mesada Ã© para este sÃ¡bado
    next_saturday = get_next_saturday()
    
    data[name] = {
        "allowance": DEFAULT_ALLOWANCE.copy(),
        "cofres": {k: 0.0 for k in DEFAULT_ALLOWANCE},
        "last_paid": next_saturday.isoformat(),
        "last_payment_date": None,
        "debt": 0.0,
        "transactions": []
    }
    save_data(data)
    return jsonify({"success": True})

@app.route('/api/child/remove', methods=['POST'])
def remove_child():
    name = request.json.get('name', '').strip()
    data = load_data()
    if name not in data:
        return jsonify({"error": "Criança não encontrada"}), 404
    del data[name]
    save_data(data)
    return jsonify({"success": True})

@app.route('/api/child/update-allowance', methods=['POST'])
def update_allowance():
    name = request.json.get('name', '').strip()
    allowance = request.json.get('allowance', {})
    data = load_data()
    if name not in data:
        return jsonify({"error": "Criança não encontrada"}), 404
    
    try:
        for k, v in allowance.items():
            allowance[k] = float(v)
        data[name]['allowance'] = allowance
        save_data(data)
        return jsonify({"success": True})
    except ValueError:
        return jsonify({"error": "Valores inválidos"}), 400

@app.route('/api/child/spend', methods=['POST'])
def spend():
    name = request.json.get('name', '').strip()
    cofre = request.json.get('cofre', '').strip()
    valor = float(request.json.get('valor', 0))
    descricao = request.json.get('descricao', '').strip()
    
    data = load_data()
    if name not in data or cofre not in data[name]['cofres']:
        return jsonify({"error": "Dados inválidos"}), 400
    
    if data[name]['cofres'][cofre] < valor:
        return jsonify({"error": "Saldo insuficiente"}), 400
    
    data[name]['cofres'][cofre] -= valor
    
    # Registar movimento
    add_transaction(data[name], 'Débito', cofre, descricao or 'Gasto', valor)
    
    save_data(data)
    return jsonify({"success": True})

@app.route('/api/child/pay', methods=['POST'])
def pay_weekly():
    """
    Confirma o pagamento semanal:
    1. Distribui a mesada pelos cofres
    2. Se há dívida, distribui de acordo com a proporÃ§Ã£o
    3. Define dívida para 0
    4. Registra data de pagamento
    5. Avança a data de próximo pagamento uma semana
    """
    name = request.json.get('name', '').strip()
    data = load_data()
    if name not in data:
        return jsonify({"error": "Criança não encontrada"}), 404
    
    today = datetime.date.today()
    last_paid = datetime.date.fromisoformat(data[name]['last_paid'])
    
    # Se ainda nÃ£o chegou a data, nÃ£o paga
    if today < last_paid:
        return jsonify({"error": "Mesada não está vencida ainda"}), 400
    
    # Distribui a mesada pelos cofres
    for cofre, valor in data[name]['allowance'].items():
        data[name]['cofres'][cofre] += valor
        # Registar movimento de crÃ©dito (mesada)
        add_transaction(data[name], 'Crédito', cofre, 'Mesada semanal', valor)
    
    # Se hÃ¡ dÃ­vida, distribui pelos cofres de acordo com a proporÃ§Ã£o
    if data[name]['debt'] > 0:
        for cofre, proporcao in DEBT_DISTRIBUTION.items():
            valor_divida = data[name]['debt'] * proporcao
            data[name]['cofres'][cofre] += valor_divida
            # Registar movimento de crÃ©dito (dÃ­vida)
            add_transaction(data[name], 'Crédito', cofre, 'Pagamento de dívida', valor_divida)
    
    # Define dÃ­vida para 0
    data[name]['debt'] = 0.0
    
    # Registra data de pagamento
    data[name]['last_payment_date'] = today.isoformat()
    
    # AvanÃ§a a data para a prÃ³xima semana
    proxima_semana = last_paid + datetime.timedelta(days=7)
    data[name]['last_paid'] = proxima_semana.isoformat()
    
    save_data(data)
    return jsonify({"success": True})

def start_flask():
    app.run(debug=False, port=5000, use_reloader=False)

if __name__ == '__main__':
    # Valida e atualiza datas na inicializaÃ§Ã£o
    validate_and_update_dates()
    
    threading.Thread(target=start_flask, daemon=True).start()
    webview.create_window("Gestão de Mesadas", "http://127.0.0.1:5000", width=1200, height=800)
    webview.start()