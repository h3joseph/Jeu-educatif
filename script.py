import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk, simpledialog
from helper.mqtt_helper import connect_mqtt, publish, subscribe
import json
import csv
import time
import hashlib

TOPIC = "dip_learning"

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def apply_retro_style(root):
    style = ttk.Style()
    style.theme_use('default')
    root.configure(bg='#1a1a1a')
    style.configure('TLabel', background='#1a1a1a', foreground='#00FFFF', font=('Courier New', 12, 'bold'))
    style.configure('TButton', background='#FF1493', foreground='#FFFFFF', font=('Courier New', 10, 'bold'), borderwidth=2, relief='flat')
    style.map('TButton', background=[('active', '#FF69B4')])
    style.configure('TEntry', fieldbackground='#333333', foreground='#00FF00', font=('Courier New', 10))
    style.configure('TFrame', background='#1a1a1a')
    style.configure('TNotebook', background='#1a1a1a', foreground='#00FFFF')
    style.configure('Neon.TButton', background='#FF1493', foreground='#FFFFFF', font=('Courier New', 10, 'bold'), bordercolor='#00FFFF', focusthickness=3, focuscolor='#00FFFF')
    style.configure('TListbox', background='#333333', foreground='#00FF00', font=('Courier New', 10))

def connect_db():
    conn = sqlite3.connect('kahoot_local.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'prof'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            type TEXT NOT NULL,
            option1 TEXT,
            option2 TEXT,
            option3 TEXT,
            option4 TEXT,
            correct_option INTEGER,
            answer_text TEXT,
            explanation TEXT NOT NULL
        )
    ''')
    conn.commit()
    cursor.execute("SELECT * FROM users WHERE username='prof'")
    if not cursor.fetchone():
        hashed_pass = hash_password('123')
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ('prof', hashed_pass, 'prof'))
        conn.commit()
        print("Utilisateur par défaut 'prof' créé avec mot de passe '123' (hashé).")
    return conn, cursor

def add_question(cursor, conn, question_text, q_type, option1, option2, option3, option4, correct_option, answer_text, explanation):
    try:
        if q_type == 'qcm':
            if not all([option1, option2, option3, option4]) or not (1 <= int(correct_option) <= 4):
                raise ValueError("QCM requires 4 options and correct_option 1-4.")
            cursor.execute('''
                INSERT INTO questions (question_text, type, option1, option2, option3, option4, correct_option, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (question_text, q_type, option1, option2, option3, option4, int(correct_option), explanation))
        elif q_type == 'ouverte':
            if not answer_text:
                raise ValueError("Ouverte requires answer_text.")
            cursor.execute('''
                INSERT INTO questions (question_text, type, answer_text, explanation)
                VALUES (?, ?, ?, ?)
            ''', (question_text, q_type, answer_text, explanation))
        else:
            raise ValueError("Type must be 'qcm' or 'ouverte'.")
        conn.commit()
        messagebox.showinfo("Succès", "Question ajoutée.")
    except ValueError as ve:
        messagebox.showerror("Erreur", str(ve))
    except Exception as e:
        messagebox.showerror("Erreur", f"Erreur ajout question: {e}")

def list_questions(cursor, text_widget):
    cursor.execute("SELECT id, question_text, type, option1, option2, option3, option4, correct_option, answer_text, explanation FROM questions")
    questions = cursor.fetchall()
    text_widget.delete(1.0, tk.END)
    text_widget.insert(tk.END, "Liste des questions:\n")
    for q in questions:
        text_widget.insert(tk.END, f"ID {q[0]}: {q[1]} (Type: {q[2]})\n")
        if q[2] == 'qcm':
            text_widget.insert(tk.END, f"Options: 1) {q[3]}, 2) {q[4]}, 3) {q[5]}, 4) {q[6]}\nBonne réponse: {q[7]}\n")
        else:
            text_widget.insert(tk.END, f"Réponse attendue: {q[8]}\n")
        text_widget.insert(tk.END, f"Explication: {q[9]}\n\n")

scores = {}
answers_received = {}
connected_students = set()

def on_message_prof(client, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        print(f"Message reçu (prof): {payload}")  # Debug
        if payload["type"] == "student_answer":
            username = payload["username"]
            qid = payload["question_id"]
            answer = payload["answer"]
            if qid not in answers_received:
                answers_received[qid] = {}
            answers_received[qid][username] = answer
        elif payload["type"] == "student_connected":
            username = payload["username"]
            connected_students.add(username)
    except Exception as e:
        print(f"Erreur réception message: {e}")

def export_scores_to_csv(scores, question_results):
    with open('scores.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Élève', 'Score', 'Total Questions', 'Questions'])
        for user, sc in scores.items():
            writer.writerow([user, sc, len(question_results), ', '.join([f"Q{qid}: {answers_received.get(qid, {}).get(user, 'Non répondu')}" for qid in question_results])])
    messagebox.showinfo("Export", "Scores exportés en scores.csv")

def play_quiz_gui(cursor, mqtt_client, quiz_tab, username, conn):
    global scores, answers_received, connected_students
    scores = {}
    answers_received = {}
    connected_students = set()
    
    num_questions = simpledialog.askinteger("Nombre de Questions", "Entrez le nombre de questions (max 21):", minvalue=1, maxvalue=21)
    if not num_questions:
        return
    
    cursor.execute("SELECT * FROM questions")
    all_questions = cursor.fetchall()
    if len(all_questions) == 0:
        messagebox.showerror("Erreur", "Aucune question disponible.")
        return
    
    # UI Elements
    label_connected = ttk.Label(quiz_tab, text="Élèves connectés: Aucun", style='TLabel')
    label_connected.pack(pady=5)
    label_progress = ttk.Label(quiz_tab, text="Quiz non démarré", style='TLabel')
    label_progress.pack(pady=5)
    label_timer = ttk.Label(quiz_tab, text="", style='TLabel')
    label_timer.pack(pady=5)
    
    listbox_questions = tk.Listbox(quiz_tab, selectmode="multiple", height=10, bg='#333333', fg='#00FF00', font=('Courier New', 10))
    listbox_questions.pack(pady=5, fill='x')
    
    question_map = {}
    for q in all_questions:
        qid = q[0]
        text = f"ID {qid}: {q[1]} (Type: {q[2]})"
        listbox_questions.insert(tk.END, text)
        question_map[listbox_questions.size() - 1] = q
    
    def confirm_selection():
        selected_indices = listbox_questions.curselection()
        if len(selected_indices) > num_questions:
            messagebox.showerror("Erreur", f"Vous ne pouvez sélectionner que {num_questions} questions.")
            return
        if len(selected_indices) == 0:
            messagebox.showerror("Erreur", "Sélectionnez au moins une question.")
            return
        
        selected_questions = [question_map[i] for i in selected_indices]
        listbox_questions.pack_forget()  # Hide listbox after selection
        start_quiz(selected_questions)
    
    ttk.Button(quiz_tab, text="Confirmer Sélection", style='Neon.TButton', command=confirm_selection).pack(pady=5)
    
    text_results = tk.Text(quiz_tab, height=15, width=60, bg='#333333', fg='#00FF00', font=('Courier New', 10), insertbackground='#00FFFF')
    text_results.pack(pady=10)
    
    def update_connected():
        label_connected.config(text=f"Élèves connectés: {', '.join(connected_students) if connected_students else 'Aucun'}")
        quiz_tab.after(1000, update_connected)
    
    update_connected()
    
    def start_quiz(questions):
        nonlocal num_questions
        num_questions = len(questions)
        question_results = {}
        current_question_index = 0
        
        def update_timer(seconds_left):
            if seconds_left > 0:
                label_timer.config(text=f"Temps restant: {seconds_left}s")
                quiz_tab.after(1000, update_timer, seconds_left - 1)
            else:
                label_timer.config(text="")
        
        def next_question():
            nonlocal current_question_index
            if current_question_index >= num_questions:
                sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                ranking = {user: rank+1 for rank, (user, _) in enumerate(sorted_scores)}
                
                text_results.delete(1.0, tk.END)
                text_results.insert(tk.END, "Résultats du quiz:\n\n")
                text_results.insert(tk.END, f"{'Élève':<20} {'Score':<10} {'Réponses'}\n")
                text_results.insert(tk.END, "-" * 50 + "\n")
                for user, sc in sorted_scores:
                    answers_str = ', '.join([f"Q{qid}: {answers_received.get(qid, {}).get(user, 'Non répondu')}" for qid in question_results])
                    text_results.insert(tk.END, f"{user:<20} {sc}/{num_questions:<10} {answers_str}\n")
                
                text_results.insert(tk.END, "\nDétails des questions:\n")
                for qid, r in question_results.items():
                    text_results.insert(tk.END, f"\nQ{qid}: {r['question']} (Type: {r['type']})\n")
                    text_results.insert(tk.END, f"Bonne réponse: {r['correct']}\nExplication: {r['explanation']}\n")
                
                publish(mqtt_client, TOPIC, {
                    "type": "quiz_end",
                    "scores": scores,
                    "ranking": ranking,
                    "results": question_results,
                    "total_questions": num_questions
                })
                label_progress.config(text="Quiz terminé !")
                export_scores_to_csv(scores, question_results)
                return
            
            q = questions[current_question_index]
            qid = q[0]
            q_type = q[2]
            question_data = {
                "id": qid,
                "question": q[1],
                "type": q_type
            }
            if q_type == 'qcm':
                question_data["options"] = [q[3], q[4], q[5], q[6]]
                correct = q[7]
                explanation = q[9]
            else:
                correct = q[8]
                explanation = q[9]
            
            question_results[qid] = {
                "question": q[1],
                "type": q_type,
                "correct": correct,
                "explanation": explanation
            }
            print(f"Envoi question: {question_data}")  # Debug
            publish(mqtt_client, TOPIC, {"type": "new_question", "data": question_data})
            label_progress.config(text=f"Question {current_question_index + 1}/{num_questions}: {q[1]} (Type: {q_type})")
            update_timer(30)
            
            def end_question():
                publish(mqtt_client, TOPIC, {"type": "end_question", "question_id": qid, "correct": correct})
                if qid in answers_received:
                    text_results.delete(1.0, tk.END)
                    text_results.insert(tk.END, f"Réponses pour Q{qid}:\n")
                    for username, ans in answers_received[qid].items():
                        if username not in scores:
                            scores[username] = 0
                        is_correct = (ans == correct) if q_type == 'qcm' else (str(ans).lower() == str(correct).lower())
                        if is_correct:
                            scores[username] += 1
                        text_results.insert(tk.END, f"{username}: {ans} ({'Correct' if is_correct else 'Incorrect'})\n")
                nonlocal current_question_index
                current_question_index += 1
                quiz_tab.after(100, next_question)
            
            quiz_tab.after(30000, end_question)
        
        next_question()
    
    def restart_quiz():
        global scores, answers_received, connected_students
        scores = {}
        answers_received = {}
        connected_students = set()
        label_progress.config(text="Quiz non démarré")
        label_timer.config(text="")
        text_results.delete(1.0, tk.END)
        listbox_questions.pack(pady=5, fill='x')
        play_quiz_gui(cursor, mqtt_client, quiz_tab, username, conn)
    
    ttk.Button(quiz_tab, text="Recommencer le Quiz", style='Neon.TButton', command=restart_quiz).pack(pady=10)

def main():
    conn, cursor = connect_db()
    root = tk.Tk()
    root.title("Interface Prof - Rétrofuturiste")
    root.geometry("800x600")
    apply_retro_style(root)
    
    main_frame = ttk.Frame(root, style='TFrame')
    main_frame.pack(expand=True, fill='both', padx=20, pady=20)
    
    def submit_login():
        username = entry_user.get()
        password = entry_pass.get()
        hashed_pass = hash_password(password)
        cursor.execute("SELECT role FROM users WHERE username=? AND password=?", (username, hashed_pass))
        result = cursor.fetchone()
        if result and result[0] == "prof":
            root.destroy()
            main_window(cursor, conn, username)
        else:
            messagebox.showerror("Erreur", "Connexion échouée.")
    
    ttk.Label(main_frame, text="Nom d'utilisateur:", style='TLabel').pack(pady=5)
    entry_user = ttk.Entry(main_frame, style='TEntry')
    entry_user.pack(pady=5)
    ttk.Label(main_frame, text="Mot de passe:", style='TLabel').pack(pady=5)
    entry_pass = ttk.Entry(main_frame, show="*", style='TEntry')
    entry_pass.pack(pady=5)
    ttk.Button(main_frame, text="Se connecter", style='Neon.TButton', command=submit_login).pack(pady=10)
    root.mainloop()
    conn.close()

def main_window(cursor, conn, username):
    root = tk.Tk()
    root.title("Gestion Quiz - Prof")
    root.geometry("800x600")
    apply_retro_style(root)
    
    notebook = ttk.Notebook(root, style='TNotebook')
    notebook.pack(fill='both', expand=True, padx=20, pady=20)
    
    questions_tab = ttk.Frame(notebook, style='TFrame')
    notebook.add(questions_tab, text="Questions")
    
    ttk.Label(questions_tab, text="Ajouter une question", style='TLabel').pack(pady=5)
    ttk.Label(questions_tab, text="Texte de la question:", style='TLabel').pack()
    entry_question = ttk.Entry(questions_tab, width=50, style='TEntry')
    entry_question.pack(pady=5)
    ttk.Label(questions_tab, text="Type (qcm / ouverte):", style='TLabel').pack()
    entry_type = ttk.Entry(questions_tab, style='TEntry')
    entry_type.pack(pady=5)
    ttk.Label(questions_tab, text="Option 1 (qcm only):", style='TLabel').pack()
    entry_opt1 = ttk.Entry(questions_tab, style='TEntry')
    entry_opt1.pack(pady=5)
    ttk.Label(questions_tab, text="Option 2 (qcm only):", style='TLabel').pack()
    entry_opt2 = ttk.Entry(questions_tab, style='TEntry')
    entry_opt2.pack(pady=5)
    ttk.Label(questions_tab, text="Option 3 (qcm only):", style='TLabel').pack()
    entry_opt3 = ttk.Entry(questions_tab, style='TEntry')
    entry_opt3.pack(pady=5)
    ttk.Label(questions_tab, text="Option 4 (qcm only):", style='TLabel').pack()
    entry_opt4 = ttk.Entry(questions_tab, style='TEntry')
    entry_opt4.pack(pady=5)
    ttk.Label(questions_tab, text="Numéro bonne option (1-4, qcm only):", style='TLabel').pack()
    entry_correct = ttk.Entry(questions_tab, style='TEntry')
    entry_correct.pack(pady=5)
    ttk.Label(questions_tab, text="Réponse attendue (ouverte only):", style='TLabel').pack()
    entry_answer = ttk.Entry(questions_tab, width=50, style='TEntry')
    entry_answer.pack(pady=5)
    ttk.Label(questions_tab, text="Explication:", style='TLabel').pack()
    entry_explanation = ttk.Entry(questions_tab, width=50, style='TEntry')
    entry_explanation.pack(pady=5)
    ttk.Button(questions_tab, text="Ajouter Question", style='Neon.TButton', command=lambda: add_question(cursor, conn, entry_question.get(), entry_type.get().lower(), entry_opt1.get(), entry_opt2.get(), entry_opt3.get(), entry_opt4.get(), entry_correct.get(), entry_answer.get(), entry_explanation.get())).pack(pady=10)
    
    ttk.Label(questions_tab, text="Liste des questions", style='TLabel').pack(pady=5)
    text_questions = tk.Text(questions_tab, height=15, width=60, bg='#333333', fg='#00FF00', font=('Courier New', 10), insertbackground='#00FFFF')
    text_questions.pack(pady=5)
    ttk.Button(questions_tab, text="Afficher Questions", style='Neon.TButton', command=lambda: list_questions(cursor, text_questions)).pack(pady=5)
    
    quiz_tab = ttk.Frame(notebook, style='TFrame')
    notebook.add(quiz_tab, text="Quiz")
    
    mqtt_client = connect_mqtt("prof_client")
    if not mqtt_client:
        root.destroy()
        conn.close()
        return
    subscribe(mqtt_client, TOPIC, on_message_prof)
    mqtt_client.loop_start()
    
    play_quiz_gui(cursor, mqtt_client, quiz_tab, username, conn)
    ttk.Button(quiz_tab, text="Changer Mot de Passe", style='Neon.TButton', command=lambda: change_password(cursor, conn, username)).pack(pady=10)
    
    root.protocol("WM_DELETE_WINDOW", lambda: [mqtt_client.loop_stop(), conn.close(), root.destroy()])
    root.mainloop()

def change_password(cursor, conn, username):
    new_pass = simpledialog.askstring("Changer Mot de Passe", "Nouveau mot de passe:", show="*")
    if new_pass:
        hashed_pass = hash_password(new_pass)
        cursor.execute("UPDATE users SET password=? WHERE username=?", (hashed_pass, username))
        conn.commit()
        messagebox.showinfo("Succès", "Mot de passe changé.")

if __name__ == "__main__":
    main()