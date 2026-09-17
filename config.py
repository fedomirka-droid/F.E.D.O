APP_NAME = "F.E.D.O"
APP_VERSION = "v1.5.6"

ASSISTANT_NAME = "F.E.D.O"
# v1.5.4: данные задаёт САМ пользователь:
#   имя — при первом запуске (или в чате: "меня зовут ...");
#   пустое имя — F.E.D.O. обращается просто "товарищ"
USER_NAME = ""
# создатель системы — можно поменять в чате: "тебя создал ..."
CREATOR = "Fedomirka"

# AI backend
AI_BACKEND = "hybrid"
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"

# Personality
ASSISTANT_STYLE = "СССР"
DEFAULT_PERSONALITY_MODE = "СССР"

# Voice
VOICE_ENABLED = True
MICROPHONE_ENABLED = False

# Safety
PUBLIC_MODE = True
PROFANITY_MODE = False
PROFANITY_TRIGGER_PHRASE = "ENABLE PROFANITY MODE"