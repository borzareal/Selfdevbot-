# Selfdevbot — ton Jarvis perso sur Telegram

Un coach de développement personnel / assistant façon Alfred (Bruce Wayne) ou Jarvis (Tony Stark),
branché sur **Gemini** (gratuit) ou l'API OpenAI. Il **t'écrit de lui-même** aux bons moments de ta journée :

> 14:00 — « Salut, n'oublie pas que tu dois aller à la salle aujourd'hui, faudrait y aller rapidement
> pour avoir le temps de taffer quand tu rentres ! »

## Pourquoi Telegram ?

| Plateforme | Bot officiel | Le bot peut écrire en premier ? | Mise en place |
|---|---|---|---|
| **Telegram** | ✅ gratuit | ✅ quand il veut | 2 minutes avec @BotFather |
| WhatsApp | API Meta Business | ⚠️ seulement dans les 24 h après ton dernier message, sinon templates payants pré-approuvés | compte Business vérifié, numéro dédié |
| Instagram | API Meta (compte pro) | ⚠️ même règle des 24 h | page Facebook + validation de l'app |
| Snapchat / iMessage | ❌ pas d'API | — | — |

Le cœur du projet, c'est que le bot envoie des messages **sans qu'on lui écrive** : Telegram est la
seule plateforme qui le permet simplement et gratuitement.

## Ce qu'il fait

- **Questionnaire d'accueil** (`/start`) : prénom, objectifs, mauvaises habitudes (et quand elles
  frappent), emploi du temps, heures de lever / coucher / repas, ville (pour le fuseau horaire),
  style de coach (doux / équilibré / strict), nombre de messages par jour.
- **Planning sur mesure** généré par l'IA : message du matin, rappels sport/travail/repas, messages
  anti-mauvaises-habitudes au bon moment, bilan du soir, rappel avant de dormir, en distinguant
  semaine et week-end.
- **Messages proactifs contextuels** : chaque message est rédigé au moment de l'envoi, en tenant
  compte de la conversation (il relance si tu n'as pas répondu, il te félicite si tu l'as déjà fait).
- **Conversation libre** avec mémoire : raconte ta journée, demande des conseils...
- **Langage naturel** : « rappelle-moi vendredi à 10h de payer le loyer », « décale mon rappel salle
  à 18h », « je me couche à minuit maintenant » : il crée ou modifie les rappels lui-même (function calling).
- Commandes : `/planning`, `/profil`, `/coach` (il t'écrit tout de suite), `/pause`, `/reprendre`,
  `/refaire`, `/oublie`, `/aide`.

## Installation

1. **Crée le bot** : sur Telegram, écris à [@BotFather](https://t.me/BotFather), `/newbot`, choisis
   un nom (ex. *Jarvis*), récupère le **token**.
2. **Clé d'IA** : au choix
   - **Gemini (gratuit)** : https://aistudio.google.com/apikey → `GEMINI_API_KEY` dans `.env`
   - OpenAI (payant) : https://platform.openai.com/api-keys → `OPENAI_API_KEY` dans `.env`
3. **Lance-le** (Python 3.11+) :

```bash
git clone <ce repo> && cd Selfdevbot-
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # puis remplis TELEGRAM_BOT_TOKEN et GEMINI_API_KEY
python main.py
```

4. Ouvre ton bot sur Telegram et tape `/start`.

> **Conseil** : mets ton ID Telegram dans `ALLOWED_USER_IDS` (demande-le à @userinfobot) pour que
> personne d'autre ne consomme ton quota d'IA.

## Le faire tourner 24h/24

Le bot doit rester allumé pour envoyer ses messages. Options simples :

- **Un VPS** (Hetzner, OVH, ~4 €/mois) : `python main.py` dans un service `systemd` ou `tmux`.
- **Railway / Render / Fly.io** : déploie le repo, commande de démarrage `python main.py`,
  ajoute les variables du `.env` dans leur interface et un volume persistant pour `DATABASE_PATH`.
- **Raspberry Pi** à la maison.

Exemple `systemd` (`/etc/systemd/system/selfdevbot.service`) :

```ini
[Unit]
Description=Selfdevbot
After=network-online.target

[Service]
WorkingDirectory=/opt/Selfdevbot-
ExecStart=/opt/Selfdevbot-/.venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## Coût

- **Gemini** : l'offre gratuite suffit pour un usage perso (attention : sur l'offre gratuite, Google
  peut utiliser les conversations pour améliorer ses modèles). Modèle par défaut `gemini-flash-latest`,
  modifiable avec `AI_MODEL`.
- **OpenAI** : avec `gpt-5-mini`, quelques centimes par jour pour un utilisateur.

## Structure

```
main.py                  démarrage du bot
selfdevbot/config.py     lecture du .env
selfdevbot/db.py         SQLite : profils, planning, rappels, historique, mémoire
selfdevbot/ai.py         persona, génération du planning, messages proactifs, chat + outils
selfdevbot/scheduler.py  envoi automatique des messages (JobQueue)
selfdevbot/handlers.py   questionnaire, commandes, conversation
selfdevbot/utils.py      heures, jours, validation
tests/                   python -m unittest discover -s tests
```

## Personnaliser

- Le caractère du coach : `Coach.persona()` dans `selfdevbot/ai.py`.
- Les questions d'accueil : `QUESTIONS` dans `selfdevbot/handlers.py`.
- Le nom : `BOT_NAME` dans `.env`.
