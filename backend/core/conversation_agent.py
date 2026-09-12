import json
import re
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
from backend.engine.db import db

class ConversationResolution(BaseModel):
    intent: str = Field(description="'FINANCIAL' | 'GREETING' | 'OUT_OF_SCOPE'")
    context_scope: str = Field(default="SINGLE_ENTITY", description="'SINGLE_ENTITY' | 'GLOBAL'")
    resolved_bank: Optional[str] = Field(default=None, description="Canonical bank name or None")
    standalone_query: str = Field(description="Fully resolved standalone query with pronouns/references substituted")
    conversational_reply: Optional[str] = Field(default=None, description="Direct friendly reply for GREETING or OUT_OF_SCOPE")

class ConversationContextAgent:
    """
    Agentic Dialogue & Context Resolver.
    Inspects multi-turn conversation history, resolves affirmations ('yes you are right'),
    detects context switches (e.g. AU Bank -> 'how many rows in db' => GLOBAL),
    and rewrites queries without brittle hardcoded regexes or static keyword lists.
    """

    def resolve(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        active_context_vendor: Optional[str] = None,
        llm_client=None
    ) -> ConversationResolution:
        canonical_banks = db.get_distinct_entities().get("banks", [])
        clean_q = query.strip()
        history = conversation_history or []

        system_prompt = (
            "You are the Conversational Context & Intent Agent for an enterprise FinOps Banking Assistant.\n"
            "Your job is to analyze the user's latest message in the context of recent conversation history to determine their intent, resolve conversational references, and output a structured JSON analysis.\n\n"
            f"Available Canonical Banks in Database:\n{json.dumps(canonical_banks)}\n\n"
            "CAPABILITIES & REASONING RULES:\n"
            "1. GENERAL GREETINGS & CHIT-CHAT:\n"
            "   - If the user says hello ('hi', 'hello', 'hey', 'good morning', etc.), asks how you are ('how are you', 'how are you doing'), or asks who you are ('who are you', 'what can you do'):\n"
            "     * Set intent = 'GREETING'\n"
            "     * Set context_scope = 'GLOBAL'\n"
            "     * Set resolved_bank = null\n"
            "     * In conversational_reply, dynamically generate a warm, professional greeting explaining that you are an enterprise FinOps Banking Assistant ready to assist with account balances, transaction tracking, payouts, and financial analytics.\n"
            "2. OUT OF SCOPE & PERSONAL QUESTIONS:\n"
            "   - If the user asks personal questions (e.g. 'what is your name', 'do you have feelings', 'who made you', 'where do you live'), or asks about non-financial topics (e.g. weather, recipes, jokes, movies, sports, trivia):\n"
            "     * Set intent = 'OUT_OF_SCOPE'\n"
            "     * Set context_scope = 'GLOBAL'\n"
            "     * Set resolved_bank = null\n"
            "     * In conversational_reply, dynamically generate polite, professional feedback explaining that you are specialized in corporate financial operations and banking datasets, and politely steer them to ask finance and banking questions.\n"
            "3. MULTI-TURN CONFIRMATIONS / AFFIRMATIONS:\n"
            "   - If the assistant previously asked for confirmation (e.g. 'Did you mean HDFC BANK LIMITED (HDFC)?') and the user confirms (e.g. 'yes', 'yes you are right', 'sure', 'correct', 'that one', 'proceed', 'go ahead'):\n"
            "     * Set intent = 'FINANCIAL'\n"
            "     * Set context_scope = 'SINGLE_ENTITY'\n"
            "     * Set resolved_bank to the confirmed bank (e.g. 'HDFC BANK LIMITED')\n"
            "     * Rewrite standalone_query to the user's original pending question with the confirmed bank name.\n"
            "4. PRONOUNS & CONTEXT INHERITANCE:\n"
            "   - If the user uses pronouns or references like 'them', 'their payouts', 'above bank', 'that bank', 'under above bank', identify which bank was discussed in the immediate previous turn and set resolved_bank to that bank.\n"
            "5. CONTEXT SWITCHES & GLOBAL DATABASE INQUIRIES:\n"
            "   - If the user asks a question about the entire database or switches away from a specific bank (e.g. 'how many rows you have in db', 'how many records in db', 'what is our overall spend', 'total balance across all accounts', 'in the database'):\n"
            "     * Set intent = 'FINANCIAL'\n"
            "     * Set context_scope = 'GLOBAL'\n"
            "     * Set resolved_bank = null (DO NOT keep the previous bank in context!)\n"
            "     * Rewrite standalone_query to clearly express the global request.\n"
            "6. FINANCIAL INQUIRIES / ACCOUNTS / PAYMENTS:\n"
            "   - Any question about balances, transactions, spend, credits, debits, UTRs, or vendor payouts:\n"
            "     * Set intent = 'FINANCIAL'\n"
            "     * Identify the bank if mentioned or inherited, else null\n"
            "     * Rewrite standalone_query into a clear, disambiguated statement.\n\n"
            "FEW-SHOT EXAMPLES:\n"
            "User: \"hi\"\n"
            "Output: {\"intent\": \"GREETING\", \"context_scope\": \"GLOBAL\", \"resolved_bank\": null, \"standalone_query\": \"hi\", \"conversational_reply\": \"Hello! I am your enterprise FinOps Banking Assistant. I can help you analyze corporate bank accounts, check balances, and track financial transactions. How can I assist you today?\"}\n\n"
            "User: \"how are you?\"\n"
            "Output: {\"intent\": \"GREETING\", \"context_scope\": \"GLOBAL\", \"resolved_bank\": null, \"standalone_query\": \"how are you?\", \"conversational_reply\": \"I'm doing well, thank you! I am ready to assist you with your financial operations, bank accounts, and transaction records. How may I help you today?\"}\n\n"
            "User: \"tell me a joke\"\n"
            "Output: {\"intent\": \"OUT_OF_SCOPE\", \"context_scope\": \"GLOBAL\", \"resolved_bank\": null, \"standalone_query\": \"tell me a joke\", \"conversational_reply\": \"I am a specialized corporate FinOps Banking Assistant designed for financial data operations and reconciliations. Please ask me questions regarding your company accounts, balances, or transactions!\"}\n\n"
            "Output valid JSON ONLY matching this schema:\n"
            "{\n"
            "  \"intent\": \"FINANCIAL\" | \"GREETING\" | \"OUT_OF_SCOPE\",\n"
            "  \"context_scope\": \"SINGLE_ENTITY\" | \"GLOBAL\",\n"
            "  \"resolved_bank\": string | null,\n"
            "  \"standalone_query\": string,\n"
            "  \"conversational_reply\": string | null\n"
            "}"
        )

        user_content = ""
        if history:
            user_content += "Recent Conversation History:\n"
            for msg in history[-6:]:
                role = "User" if msg.get("role") == "user" else "Assistant"
                user_content += f"- {role}: {msg.get('content', '')[:200]}\n"
        if active_context_vendor:
            user_content += f"Active Bank in Context: '{active_context_vendor}'\n"
        user_content += f"Current User Message: \"{clean_q}\"\n"

        # 1. Try LLM (Bedrock / Ollama / Groq)
        if llm_client:
            try:
                raw = llm_client.complete(user_content, system_prompt)
                clean_raw = raw.strip() if raw else ""
                if "```json" in clean_raw:
                    clean_raw = clean_raw.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_raw:
                    clean_raw = clean_raw.split("```")[1].split("```")[0].strip()

                match = re.search(r'\{.*\}', clean_raw, re.DOTALL)
                json_str = match.group(0) if match else clean_raw
                parsed = json.loads(json_str)

                intent = str(parsed.get("intent") or "FINANCIAL").strip().upper()
                if intent not in ["FINANCIAL", "GREETING", "OUT_OF_SCOPE"]:
                    intent = "FINANCIAL"

                raw_scope = parsed.get("context_scope")
                scope = str(raw_scope).strip().upper() if raw_scope else "SINGLE_ENTITY"
                if scope not in ["SINGLE_ENTITY", "GLOBAL"]:
                    scope = "GLOBAL" if "global" in str(parsed).lower() else "SINGLE_ENTITY"

                bank = parsed.get("resolved_bank")
                if bank and not any(str(bank).upper() == b.upper() for b in canonical_banks):
                    # Check fuzzy match against canonical banks
                    from rapidfuzz import process, fuzz
                    m = process.extractOne(str(bank), canonical_banks, scorer=fuzz.token_set_ratio)
                    bank = m[0] if m and m[1] >= 75 else None

                sq = parsed.get("standalone_query") or clean_q
                cr = parsed.get("conversational_reply")

                # Default fallback reply if LLM categorized as GREETING / OUT_OF_SCOPE but omitted text
                if intent == "GREETING" and not cr:
                    cr = "Hello! I am your enterprise FinOps Banking Assistant. How can I assist you with your financial operations, bank accounts, or transaction records today?"
                elif intent == "OUT_OF_SCOPE" and not cr:
                    cr = "I am an enterprise FinOps Banking Assistant specialized in corporate banking datasets, account balances, and financial transactions. Please feel free to ask any finance-related questions!"

                return ConversationResolution(
                    intent=intent,
                    context_scope=scope,
                    resolved_bank=bank,
                    standalone_query=str(sq),
                    conversational_reply=cr
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"LLM intent resolution parsing failed: {e}. Raw: {raw if 'raw' in locals() else None}")

        # 2. Intelligent Deterministic Fallback (for testing / offline)
        return self._deterministic_fallback(clean_q, history, active_context_vendor, canonical_banks)

    def _deterministic_fallback(
        self,
        query: str,
        history: List[Dict[str, str]],
        active_vendor: Optional[str],
        canonical_banks: List[str]
    ) -> ConversationResolution:
        lower = query.lower().strip()

        # Deterministic fallback handles ONLY core financial scoping logic.
        # Greetings and personal/out-of-scope intent classification is now handled purely by the LLM Intent Agent.

        # Check Affirmations after clarification
        last_asst = history[-1]["content"] if history and history[-1].get("role") == "assistant" else ""
        is_affirmation = any(lower == a or lower.startswith(a + " ") for a in [
            "yes", "yep", "yeah", "yup", "correct", "right", "yes you are right",
            "you are right", "that's right", "thats right", "sure", "confirm", "confirmed",
            "proceed", "go ahead", "ok", "okay", "please", "yes please"
        ])

        if is_affirmation and "Did you mean" in last_asst:
            # Extract suggested entity from assistant message
            for b in canonical_banks:
                if b.lower() in last_asst.lower():
                    prev_user_q = history[-2]["content"] if len(history) >= 2 and history[-2].get("role") == "user" else f"Show balance for {b}"
                    sq = prev_user_q
                    from backend.core.entity_resolver import entity_resolver
                    aliases = list(entity_resolver.dynamic_aliases.keys())
                    if aliases:
                        pattern = r"\b(" + "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True)) + r")\b"
                        sq = re.sub(pattern, b, sq, flags=re.IGNORECASE)
                    if b.lower() not in sq.lower():
                        sq += f" for {b}"
                    return ConversationResolution(
                        intent="FINANCIAL",
                        context_scope="SINGLE_ENTITY",
                        resolved_bank=b,
                        standalone_query=sq,
                        conversational_reply=None
                    )

        # Check Global / Sizing questions
        if any(w in lower for w in ["how many rows", "rows in db", "records in db", "in the database", "in db", "total records", "all banks", "across all"]):
            return ConversationResolution(
                intent="FINANCIAL",
                context_scope="GLOBAL",
                resolved_bank=None,
                standalone_query="How many total records and accounts are in the database?",
                conversational_reply=None
            )

        # Check Date inquiries for previous records
        if any(w in lower for w in ["which date", "what date", "on which date", "when were", "what are the dates"]):
            last_vendor = active_vendor
            if not last_vendor and history:
                for b in canonical_banks:
                    if b.lower() in history[-1].get("content", "").lower():
                        last_vendor = b
                        break
            return ConversationResolution(
                intent="FINANCIAL",
                context_scope="SINGLE_ENTITY" if last_vendor else "GLOBAL",
                resolved_bank=last_vendor,
                standalone_query=f"Show transaction records and dates for {last_vendor}" if last_vendor else "Show transaction records and dates",
                conversational_reply=None
            )

        # Check Pronouns ("above bank", "that bank", "them")
        if any(w in lower for w in ["above bank", "that bank", "them", "their"]):
            last_vendor = active_vendor
            if not last_vendor and history:
                for b in canonical_banks:
                    if b.lower() in history[-1].get("content", "").lower():
                        last_vendor = b
                        break
            if last_vendor:
                sq = re.sub(r"\b(above bank|that bank|them|their)\b", last_vendor, query, flags=re.IGNORECASE)
                return ConversationResolution(
                    intent="FINANCIAL",
                    context_scope="SINGLE_ENTITY",
                    resolved_bank=last_vendor,
                    standalone_query=sq,
                    conversational_reply=None
                )

        # Check creditor description inquiries / who paid
        if any(w in lower for w in ["in the description", "creditor name", "who paid", "who credited", "incoming payments"]):
            last_vendor = active_vendor or (canonical_banks[0] if canonical_banks else "HDFC BANK LIMITED")
            for b in canonical_banks:
                if b.lower() in lower:
                    last_vendor = b
                    break
            return ConversationResolution(
                intent="FINANCIAL",
                context_scope="SINGLE_ENTITY",
                resolved_bank=last_vendor,
                standalone_query=f"Show incoming credit transactions and check description for creditor names for {last_vendor}",
                conversational_reply=None
            )

        # Check account listing inquiries
        if any(w in lower for w in ["how many accounts", "how many accoutns", "which accounts", "accounts under"]):
            last_vendor = active_vendor or (canonical_banks[0] if canonical_banks else "HDFC BANK LIMITED")
            for b in canonical_banks:
                if b.lower() in lower:
                    last_vendor = b
                    break
            return ConversationResolution(
                intent="FINANCIAL",
                context_scope="SINGLE_ENTITY",
                resolved_bank=last_vendor,
                standalone_query=f"List all accounts, program IDs, and available balances under {last_vendor}",
                conversational_reply=None
            )

        # Check explicit bank mentions
        for b in canonical_banks:
            if b.lower() in lower:
                return ConversationResolution(
                    intent="FINANCIAL",
                    context_scope="SINGLE_ENTITY",
                    resolved_bank=b,
                    standalone_query=query,
                    conversational_reply=None
                )

        return ConversationResolution(
            intent="FINANCIAL",
            context_scope="GLOBAL",
            resolved_bank=None,
            standalone_query=query,
            conversational_reply=None
        )

conversation_agent = ConversationContextAgent()
