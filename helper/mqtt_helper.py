import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
import json
import time

PORT = 1883

def connect_mqtt(client_id, broker="localhost"):
    client = mqtt.Client(client_id=client_id, callback_api_version=CallbackAPIVersion.VERSION2)
    for _ in range(3):
        try:
            client.connect(broker, PORT)
            print(f"Connecté au broker MQTT à {broker}:{PORT}")
            return client
        except Exception as e:
            print(f"Erreur connexion MQTT: {e}. Nouvelle tentative dans 2s...")
            time.sleep(2)
    print("Échec de connexion au broker après plusieurs tentatives.")
    return None

def publish(client, topic, message):
    if client:
        try:
            client.publish(topic, json.dumps(message))
        except Exception as e:
            print(f"Erreur publication MQTT: {e}")

def subscribe(client, topic, on_message):
    if client:
        try:
            client.subscribe(topic)
            client.on_message = on_message
        except Exception as e:
            print(f"Erreur subscription MQTT: {e}")