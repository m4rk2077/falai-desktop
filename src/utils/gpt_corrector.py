"""
GPT Corrector - Auto-correct transcriptions using GPT
"""
from openai import OpenAI
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class GPTCorrector:
    """Corrects transcriptions using GPT for better punctuation and grammar"""
    
    STYLES = {
        "neutro": (
            "Adicione APENAS pontuação (pontos, vírgulas, interrogações, exclamações) "
            "e maiúsculas no início de frases. NÃO mude nenhuma palavra."
        ),
        "casual": (
            "Corrija pontuação, espaçamento e capitalização. "
            "Mantenha gírias e expressões informais. Corrija apenas erros claros de ortografia."
        ),
        "formal": (
            "Reescreva em português formal e profissional. "
            "Corrija gramática, concordância e pontuação. Substitua gírias por equivalentes formais."
        ),
    }
    
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o-mini"  # Fast and cheap
    
    def correct(self, text: str, style: str = "neutro") -> Optional[str]:
        """
        Correct transcription text using GPT
        
        Args:
            text: Raw transcription from Whisper
            style: Correction style (casual, formal, neutro)
        
        Returns:
            Corrected text or None if error
        """
        if not text or len(text.strip()) == 0:
            return text
        
        style_instruction = self.STYLES.get(style, self.STYLES["neutro"])
        
        prompt = f"""Corrija o texto transcrito abaixo. 
{style_instruction}

Regras:
- Adicione pontuação adequada (vírgulas, pontos, interrogações)
- Corrija capitalização (início de frases, nomes próprios)
- Corrija erros de ortografia óbvios
- NÃO mude o significado ou adicione palavras
- Preserve exatamente palavras em inglês, nomes de marcas, produtos, plataformas, siglas e nomes próprios
- NÃO traduza ou substitua termos como Facebook, Instagram, WhatsApp, Meta, Google Ads, CRM, lead, briefing, call, dashboard, direct, story, feed e reels
- NÃO adicione explicações, retorne APENAS o texto corrigido

Texto: {text}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Você é um corretor de texto. Retorne apenas o texto corrigido, sem explicações."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Low temperature for consistency
                max_tokens=1000
            )
            
            corrected = response.choices[0].message.content.strip()
            
            # Remove quotes if GPT added them
            if corrected.startswith('"') and corrected.endswith('"'):
                corrected = corrected[1:-1]
            
            logger.info("GPT correction applied")
            return corrected
            
        except Exception as e:
            logger.error("GPT correction error", exc_info=True)
            return text  # Return original if error
