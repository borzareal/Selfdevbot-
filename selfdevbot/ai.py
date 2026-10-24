"""Tout ce qui parle à l'API OpenAI : persona, génération du planning, messages proactifs, chat."""

import json
import logging
from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from openai import AsyncOpenAI

from .utils import DAY_NAMES, format_days

log = logging.getLogger(__name__)

ToolExecutor = Callable[[str, dict], Awaitable[dict]]

PROFILE_LABELS = {
    "name": "Prénom",
    "goals": "Objectifs",
    "bad_habits": "Mauvaises habitudes",
    "schedule": "Emploi du temps",
    "wake_time": "Réveil",
    "bed_time": "Coucher",
    "meals": "Repas",
    "city": "Ville",
    "tone": "Style de coaching voulu",
    "frequency": "Fréquence de messages voulue",
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Programme un rappel ponctuel (une seule fois) à une date/heure précise.",
            "parameters": {
                "type": "object",
                "properties": {
                    "when": {"type": "string", "description": "Date/heure locale ISO, ex: 2026-10-24T18:30"},
                    "text": {"type": "string", "description": "Ce dont il faut lui parler à ce moment-là"},
                },
                "required": ["when", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_recurring_checkin",
            "description": "Ajoute un message récurrent que tu enverras automatiquement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {"type": "string", "description": "HH:MM heure locale"},
                    "days": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "0 = lundi ... 6 = dimanche",
                    },
                    "purpose": {"type": "string", "description": "Objet du message"},
                },
                "required": ["time", "days", "purpose"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_checkin",
            "description": "Supprime un message récurrent par son id.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": "Annule un rappel ponctuel en attente par son id.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_profile",
            "description": "Met à jour une info du profil quand l'utilisateur change quelque chose (horaires, objectifs...).",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(PROFILE_LABELS)},
                    "value": {"type": "string"},
                },
                "required": ["field", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Mémorise un fait important et durable sur l'utilisateur (progrès, préférence, événement).",
            "parameters": {
                "type": "object",
                "properties": {"fact": {"type": "string"}},
                "required": ["fact"],
            },
        },
    },
]


def format_profile(profile: dict) -> str:
    return "\n".join(f"- {label} : {profile[k]}" for k, label in PROFILE_LABELS.items() if profile.get(k))


class Coach:
    def __init__(self, api_key: str, model: str, bot_name: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.bot_name = bot_name

    async def _complete(self, messages: list[dict], **kwargs):
        resp = await self.client.chat.completions.create(model=self.model, messages=messages, **kwargs)
        return resp.choices[0].message

    def persona(self, user: dict, now_local: datetime, memories: list[str], checkins: list[dict],
                reminders: list[dict]) -> str:
        profile = user["profile"]
        name = profile.get("name") or user.get("first_name") or "toi"
        lines = [
            f"Tu es {self.bot_name}, l'assistant personnel et coach de développement personnel de {name}, "
            "dans l'esprit d'Alfred pour Bruce Wayne et de Jarvis pour Tony Stark : loyal, lucide, "
            "un brin d'humour pince-sans-rire, toujours de son côté mais sans complaisance.",
            "Tu parles français, en tutoyant, comme dans une vraie conversation par texto : "
            "messages courts, naturels, pas de listes à rallonge, pas de formules de robot.",
            "Ton rôle : l'aider à tenir ses objectifs, casser ses mauvaises habitudes, respecter son "
            "rythme (sommeil, repas, sport, travail). Tu poses des questions de suivi, tu félicites les "
            "progrès concrets et tu recadres avec bienveillance quand il dérive.",
            "Tu peux programmer des rappels et des messages récurrents via tes outils : utilise-les dès "
            "qu'il te demande de lui rappeler quelque chose ou de changer ses horaires. Mémorise les faits "
            "importants avec l'outil remember.",
            "Tu n'es pas médecin ni psy : si tu détectes une détresse sérieuse, encourage-le avec douceur "
            "à en parler à un proche ou un professionnel.",
            "",
            f"Maintenant : {DAY_NAMES[now_local.weekday()]} {now_local:%Y-%m-%d %H:%M} ({user['timezone']}).",
            "",
            "PROFIL :",
            format_profile(profile) or "(vide)",
        ]
        if user.get("plan_summary"):
            lines += ["", "STRATÉGIE DE COACHING :", user["plan_summary"]]
        if memories:
            lines += ["", "CE QUE TU SAIS DE LUI :"] + [f"- {m}" for m in memories]
        if checkins:
            lines += ["", "TES MESSAGES AUTOMATIQUES (id, heure, jours, objet) :"]
            lines += [f"- #{c['id']} {c['time']} {format_days(c['days'])} : {c['purpose']}" for c in checkins]
        if reminders:
            tz = ZoneInfo(user["timezone"])
            lines += ["", "RAPPELS PONCTUELS EN ATTENTE (id, quand, objet) :"]
            lines += [f"- #{r['id']} {datetime.fromisoformat(r['run_at']).astimezone(tz):%Y-%m-%d %H:%M} : {r['text']}"
                      for r in reminders]
        return "\n".join(lines)

    async def build_plan(self, profile: dict, max_per_day: int) -> dict:
        """Transforme les réponses de l'onboarding en planning de messages automatiques."""
        prompt = f"""Voici le profil d'une personne qui veut un coach personnel par messages :
{format_profile(profile)}

Conçois son planning de messages automatiques que le coach lui enverra de lui-même.
Règles :
- Au maximum {max_per_day} messages par jour, adaptés à son emploi du temps (semaine vs week-end).
- Inclure : un message au réveil (motivation + priorités du jour), des rappels aux moments clés de
  son emploi du temps (sport, travail/études, repas), des messages placés AU MOMENT où ses mauvaises
  habitudes frappent d'habitude, un bilan du soir, et un rappel 30-45 min avant l'heure du coucher.
- Ne jamais envoyer de message pendant ses heures de sommeil.
- "purpose" décrit précisément ce que le coach doit dire/demander, en lien avec SES objectifs.
- days : 0 = lundi ... 6 = dimanche.
- timezone : fuseau IANA déduit de sa ville (ex: Europe/Paris, America/Montreal). Si inconnu : null.
- summary : 3-5 phrases de stratégie de coaching pour cette personne (priorités, points de vigilance, ton).

Réponds UNIQUEMENT en JSON :
{{"timezone": "...", "summary": "...", "checkins": [{{"time": "HH:MM", "days": [0,1,2,3,4], "purpose": "..."}}]}}"""
        msg = await self._complete(
            [{"role": "user", "content": prompt}], response_format={"type": "json_object"}
        )
        try:
            return json.loads(msg.content or "{}")
        except json.JSONDecodeError:
            log.warning("Plan JSON invalide : %s", msg.content)
            return {}

    async def proactive_message(self, system: str, history: list[dict], purpose: str) -> str:
        """Message envoyé à l'initiative du bot (check-in planifié ou rappel)."""
        instruction = (
            f"[Interne — l'utilisateur ne voit pas ceci] C'est le moment de lui écrire de toi-même. "
            f"Objet : {purpose}\n"
            "Écris UN message court (1 à 4 phrases), naturel, comme un texto d'un assistant qui le connaît. "
            "Tiens compte de la conversation récente (s'il n'a pas répondu à ton dernier message, "
            "relance autrement ; s'il a déjà fait la chose, félicite au lieu de rappeler). "
            "Ne dis pas que c'est un message programmé."
        )
        messages = [{"role": "system", "content": system}, *_history(history),
                    {"role": "system", "content": instruction}]
        msg = await self._complete(messages)
        return (msg.content or "").strip()

    async def chat(self, system: str, history: list[dict], user_text: str, execute: ToolExecutor) -> str:
        messages = [{"role": "system", "content": system}, *_history(history),
                    {"role": "user", "content": user_text}]
        for _ in range(5):
            msg = await self._complete(messages, tools=TOOLS)
            if not msg.tool_calls:
                return (msg.content or "").strip()
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in msg.tool_calls
                ],
            })
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                    result = await execute(call.function.name, args)
                except Exception as e:  # le modèle doit voir l'erreur pour se corriger
                    log.exception("Outil %s en échec", call.function.name)
                    result = {"ok": False, "error": str(e)}
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(result, ensure_ascii=False)})
        msg = await self._complete(messages)
        return (msg.content or "").strip()


def _history(history: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": m["content"]} for m in history if m["role"] in ("user", "assistant")]
