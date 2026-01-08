import threading
from flask import Flask, request, jsonify
from embedding import handle_create, handle_update, handle_delete

app = Flask(__name__)

@app.route('/events', methods=['POST'])
def handle_aas_event():
    event = request.get_json()
    if not event:
        return jsonify({"status": "error", "message": "Kein JSON"}), 400

    event_type = str(event.get("type", "")).upper()
    
    if event_type.endswith("_CREATED"):
        target_func = handle_create
    elif event_type.endswith("_UPDATED"):
        target_func = handle_update
    elif event_type.endswith("_DELETED"):
        target_func = handle_delete
    else:
        return jsonify({"status": "ignored", "message": f"Type {event_type} not supported"}), 200

    thread = threading.Thread(target=target_func, args=(event,))
    thread.daemon = True
    thread.start()

    return jsonify({"status": "accepted"}), 202

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "online"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)