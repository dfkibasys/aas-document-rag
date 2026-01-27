from flask import Flask, request, jsonify
from embedding import handle_create, handle_update, handle_delete

app = Flask(__name__)

@app.route('/events', methods=['POST'])
def handle_aas_event():
    event = request.get_json()
    if not event:
        return jsonify({"status": "error", "message": "Kein JSON"}), 400

    event_type = str(event.get("type", "")).upper()
    
    target_func = None
    if event_type.endswith("_CREATED"):
        target_func = handle_create
    elif event_type.endswith("_UPDATED"):
        target_func = handle_update
    elif event_type.endswith("_DELETED"):
        target_func = handle_delete
    else:
        return jsonify({"status": "ignored", "message": f"Type {event_type} not supported"}), 400

    try:
        target_func(event)
        return jsonify({"status": "success", "message": "Event erfolgreich verarbeitet"}), 200
    except Exception as e:
        app.logger.error(f"Fehler bei der Event-Verarbeitung: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Fehler bei der Event-Verarbeitung: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "online"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)