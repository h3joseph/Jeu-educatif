import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from helper.mqtt_helper import connect_mqtt, subscribe, publish
import json

TOPIC = "dip_learning"

answers = {}
quiz_active = True
current_question_id = None

def apply_retro_style(root):
    style = ttk.Style()
    style.theme_use('default')
    root.configure(bg='#1a1a1a')
    style.configure('TLabel', background='#1a1a1a', foreground='#00FFFF', font=('Courier New', 12, 'bold'))
    style.configure('TButton', background='#FF1493', foreground='#FFFFFF', font=('Courier New', 10, 'bold'), borderwidth=2, relief='flat')
    style.map('TButton', background=[('active', '#FF69B4')])
    style.configure('TEntry', fieldbackground='#333333', foreground='#00FF00', font=('Courier New', 10))
    style.configure('TFrame', background='#1a1a1a')
    style.configure('Neon.TButton', background='#FF1493', foreground='#FFFFFF', font=('Courier New', 10, 'bold'), bordercolor='#00FFFF', focusthickness=3, focuscolor='#00FFFF')

def connect_db():
    conn = sqlite3.connect('kahoot_local.db')
    cursor = conn.cursor()
    return conn, cursor

def main():
    root = tk.Tk()
    root.title("Quiz Élève - Rétrofuturiste")
    root.geometry("800x600")
    apply_retro_style(root)
    
    main_frame = ttk.Frame(root, style='TFrame')
    main_frame.pack(expand=True, fill='both', padx=20, pady=20)
    
    # Login Section
    login_frame = ttk.Frame(main_frame, style='TFrame')
    login_frame.pack(pady=10)
    
    ttk.Label(login_frame, text="Votre nom:", style='TLabel').pack(pady=5)
    entry_user = ttk.Entry(login_frame, style='TEntry')
    entry_user.pack(pady=5)
    
    ttk.Label(login_frame, text="IP du prof (ex: 192.168.1.1):", style='TLabel').pack(pady=5)
    entry_broker = ttk.Entry(login_frame, style='TEntry')
    entry_broker.pack(pady=5)
    
    label_status = ttk.Label(main_frame, text="Connectez-vous pour commencer...", style='TLabel')
    label_status.pack(pady=10)
    
    label_question = ttk.Label(main_frame, text="Attente question...", wraplength=600, style='TLabel')
    label_question.pack(pady=10)
    
    label_timer = ttk.Label(main_frame, text="", style='TLabel')
    label_timer.pack(pady=5)
    
    frame_answer = ttk.Frame(main_frame, style='TFrame')
    frame_answer.pack(pady=10)
    
    text_results = tk.Text(main_frame, height=15, width=60, bg='#333333', fg='#00FF00', font=('Courier New', 10), insertbackground='#00FFFF')
    text_results.pack(pady=10)
    
    buttons = []
    for i in range(1, 5):
        btn = ttk.Button(frame_answer, text=f"Option {i}", style='Neon.TButton', state="disabled")
        btn.pack(side=tk.LEFT, padx=5)
        buttons.append(btn)
    
    entry_open = ttk.Entry(frame_answer, width=50, style='TEntry', state="disabled")
    entry_open.pack(side=tk.LEFT, padx=5)
    btn_submit = ttk.Button(frame_answer, text="Envoyer", style='Neon.TButton', state="disabled")
    btn_submit.pack(side=tk.LEFT, padx=5)
    
    def connect_and_start():
        username = entry_user.get()
        broker = entry_broker.get()
        if not username or not broker:
            messagebox.showerror("Erreur", "Entrez nom et IP.")
            return
        mqtt_client = connect_mqtt(f"eleve_{username}", broker)
        if not mqtt_client:
            messagebox.showerror("Erreur", "Connexion MQTT échouée.")
            return
        
        login_frame.pack_forget()  # Hide login frame
        label_status.config(text=f"Connecté ! En attente du quiz...")
        publish(mqtt_client, TOPIC, {"type": "student_connected", "username": username})
        print(f"Élève {username} connecté")  # Debug
        
        def update_timer(seconds_left):
            if seconds_left > 0:
                label_timer.config(text=f"Temps restant: {seconds_left}s")
                root.after(1000, update_timer, seconds_left - 1)
            else:
                label_timer.config(text="")
        
        def on_message(client, userdata, msg):
            global quiz_active, current_question_id
            try:
                payload = json.loads(msg.payload)
                print(f"Message reçu (élève): {payload}")  # Debug
                if payload["type"] == "new_question":
                    q = payload["data"]
                    current_question_id = q["id"]
                    q_type = q["type"]
                    label_question.config(text=f"Q{current_question_id}: {q['question']}")
                    if q_type == 'qcm':
                        label_question.config(text=label_question.cget("text") + "\n" + "\n".join(f"{i}: {opt}" for i, opt in enumerate(q["options"], 1)))
                        for btn in buttons:
                            btn.config(state="normal")
                        entry_open.config(state="disabled")
                        btn_submit.config(state="disabled")
                    else:
                        for btn in buttons:
                            btn.config(state="disabled")
                        entry_open.config(state="normal")
                        btn_submit.config(state="normal")
                    update_timer(30)
                    def timer():
                        global answers, current_question_id
                        if current_question_id and current_question_id not in answers:
                            answers[current_question_id] = None
                            label_question.config(text=label_question.cget("text") + "\nTemps écoulé !")
                    root.after(30000, timer)
                elif payload["type"] == "end_question":
                    qid = payload["question_id"]
                    correct = payload["correct"]
                    for btn in buttons:
                        btn.config(state="disabled")
                    entry_open.config(state="disabled")
                    btn_submit.config(state="disabled")
                    label_question.config(text=f"Q{qid} terminée. Bonne réponse: {correct}\nVotre réponse: {answers.get(qid, 'Non répondu')}")
                    label_timer.config(text="")
                    current_question_id = None
                elif payload["type"] == "quiz_end":
                    quiz_active = False
                    text_results.delete(1.0, tk.END)
                    text_results.insert(tk.END, f"Quiz terminé ! Votre score: {payload['scores'].get(username, 0)} / {payload['total_questions']}\nClassement: {payload['ranking'].get(username, 'N/A')}\n\nVos erreurs:\n")
                    conn, cursor = connect_db()
                    for qid, r in payload["results"].items():
                        your_ans = answers.get(qid)
                        correct = r["correct"]
                        is_correct = (your_ans == correct) if r["type"] == 'qcm' else (str(your_ans).lower() == str(correct).lower() if your_ans else False)
                        if not is_correct:
                            text_results.insert(tk.END, f"Q{qid}: {r['question']} (Type: {r['type']})\nVotre réponse: {your_ans if your_ans else 'Non répondu'}\nBonne réponse: {correct}\nExplication: {r['explanation']}\n\n")
                    conn.close()
                    label_status.config(text="Quiz terminé !")
                    ttk.Button(main_frame, text="Quitter", style='Neon.TButton', command=lambda: [mqtt_client.loop_stop(), root.destroy()]).pack(pady=10)
            except Exception as e:
                print(f"Erreur réception message: {e}")
        
        def send_answer(ans):
            global current_question_id
            if current_question_id and current_question_id not in answers:
                answers[current_question_id] = ans
                publish(mqtt_client, TOPIC, {"type": "student_answer", "username": username, "question_id": current_question_id, "answer": ans})
                label_status.config(text=f"Réponse {ans} envoyée !")
                print(f"Réponse envoyée: Q{current_question_id}, {ans}")  # Debug
        
        for i, btn in enumerate(buttons, 1):
            btn.config(command=lambda i=i: send_answer(i))
        
        def submit_open():
            ans = entry_open.get()
            if ans:
                send_answer(ans)
                entry_open.delete(0, tk.END)
        
        btn_submit.config(command=submit_open)
        
        subscribe(mqtt_client, TOPIC, on_message)
        mqtt_client.loop_start()
    
    ttk.Button(login_frame, text="Connexion", style='Neon.TButton', command=connect_and_start).pack(pady=10)
    root.mainloop()

if __name__ == "__main__":
    main()