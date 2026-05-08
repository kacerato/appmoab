"""
AquaMoab — Webhooks Router.
Recebe requisições de serviços externos, como o nosso microserviço de WhatsApp.
"""

from fastapi import APIRouter, Request, BackgroundTasks
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe mensagens do microserviço Evolution API.
    """
    try:
        payload = await request.json()
        
        # O Evolution API envia vários eventos. Só queremos mensagens recebidas.
        event = payload.get("event")
        if event != "messages.upsert":
            return {"status": "ignored", "reason": "not a message upsert"}
            
        data = payload.get("data", {})
        key = data.get("key", {})
        
        if key.get("fromMe"):
            return {"status": "ignored", "reason": "message sent by me"}
            
        remote_jid = key.get("remoteJid", "")
        phone = remote_jid.split("@")[0]
        
        message_obj = data.get("message", {})
        
        # Pega texto simples ou estendido
        body = ""
        if "conversation" in message_obj:
            body = message_obj["conversation"]
        elif "extendedTextMessage" in message_obj:
            body = message_obj["extendedTextMessage"].get("text", "")
            
        if not body:
            return {"status": "ignored", "reason": "empty or unsupported message type"}
        
        logger.info(f"Nova mensagem (Evolution API) de {phone}: {body}")
        
        # Aqui no futuro você integrará com o Kimi (Moonshot AI)
        # background_tasks.add_task(process_whatsapp_message_with_ai, phone, body)
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Erro no webhook do WhatsApp: {e}")
        return {"status": "error", "message": str(e)}
