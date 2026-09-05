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
            "1. MULTI-TURN CONFIRMATIONS / AFFIRMATIONS:\n"
            "   - If the assistant previously asked for confirmation (e.g. 'Did you mean HDFC BANK LIMITED (HDFC)?') and the user confirms (e.g. 'yes', 'yes you are right', 'sure', 'correct', 'that one', 'proceed', 'go ahead'):\n"
            "     * Set intent = 'FINANCIAL'\n"
            "     * Set context_scope = 'SINGLE_ENTITY'\n"
            "     * Set resolved_bank to the confirmed bank (e.g. 'HDFC BANK LIMITED')\n"
            "     * Rewrite standalone_query to the user's original pending question with the confirmed bank name.\n"
            "2. PRONOUNS & CONTEXT INHERITANCE:\n"
            "   - If the user uses pronouns or references like 'them', 'their payouts', 'above bank', 'that bank', 'under above bank', identify which bank was discussed in the immediate previous turn and set resolved_bank to that bank.\n"
            "3. CONTEXT SWITCHES & GLOBAL DATABASE INQUIRIES:\n"
            "   - If the user asks a question about the entire database or switches away from a specific bank (e.g. 'how many rows you have in db', 'how many records in db', 'what is our overall spend', 'total balance across all accounts', 'in the database'):\n"
            "     * Set intent = 'FINANCIAL'\n"
            "     * Set context_scope = 'GLOBAL'\n"
            "     * Set resolved_bank = null (DO NOT keep the previous bank in context!)\n"
            "     * Rewrite standalone_query to clearly express the global request (e.g. 'How many total rows or records are in the database across all accounts and transactions?').\n"
            "4. WHO PAID / INCOMING PAYMENTS / CREDITOR DESCRIPTIONS:\n"
            "   - When user asks 'who paid to <bank>', 'who paid us', or says 'in the description we have the creditor name. check and give':\n"
            "     * Set intent = 'FINANCIAL'\n"
            "     * Set context_scope = 'SINGLE_ENTITY'\n"
            "     * Set resolved_bank to the relevant bank (e.g. 'HDFC BANK LIMITED')\n"
            "     * Rewrite standalone_query to 'Show incoming credit transactions and check description for creditor names for <bank>'.\n"
            "   - When user asks 'how many accounts we have under <bank>' or 'what accounts do we have under <bank>':\n"
            "     * Set intent = 'FINANCIAL'\n"
            "     * Set context_scope = 'SINGLE_ENTITY'\n"
            "     * Set resolved_bank to the bank\n"
            "     * Rewrite standalone_query to 'List all accounts, program IDs, and available balances under <bank>'.\n"
            "5. RECORD & DATE DETAILS:\n"
            "   - If the user asks what dates records occurred on (e.g. 'all these three records are on which date', 'when did this happen'):\n"
            "     * Keep the relevant bank in scope.\n"
            "     * Rewrite standalone_query to ask for the dates and details of those records without restricting to an arbitrary single date.\n"
            "6. GENERAL GREETINGS & CHIT-CHAT:\n"
            "   - If the user says hello, asks who you are, or asks for general help ('hi', 'hello', 'good morning', 'who are you', 'what can you do', 'help', 'thank you'):\n"
            "     * Set intent = 'GREETING'\n"
            "     * Provide a helpful, professional greeting in conversational_reply explaining your capabilities (bank accounts, available balances, transaction tracking, credit/debit breakdowns, reference lookups).\n"
            "7. OUT OF SCOPE:\n"
            "   - If the user asks about completely unrelated topics (weather, recipes, poems, jokes, general knowledge, movies, sports):\n"
            "     * Set intent = 'OUT_OF_SCOPE'\n"
            "     * Provide a polite conversational_reply explaining that you are specialized in corporate financial and banking datasets.\n\n"
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
                match = re.search(r'\{.*\}', raw, re.DOTALL)
                json_str = match.group(0) if match else raw
                parsed = json.loads(json_str)

                intent = parsed.get("intent", "FINANCIAL").upper()
                if intent not in ["FINANCIAL", "GREETING", "OUT_OF_SCOPE"]:
                    intent = "FINANCIAL"

                scope = parsed.get("context_scope", "SINGLE_ENTITY").upper()
                if scope not in ["SINGLE_ENTITY", "GLOBAL"]:
                    scope = "GLOBAL" if "global" in str(parsed).lower() else "SINGLE_ENTITY"

                bank = parsed.get("resolved_bank")
                if bank and not any(bank.upper() == b.upper() for b in canonical_banks):
                    # Check fuzzy match against canonical banks
                    from rapidfuzz import process, fuzz
                    m = process.extractOne(bank, canonical_banks, scorer=fuzz.token_set_ratio)
                    bank = m[0] if m and m[1] >= 75 else None

                sq = parsed.get("standalone_query") or clean_q
                cr = parsed.get("conversational_reply")

                return ConversationResolution(
                    intent=intent,
                    context_scope=scope,
                    resolved_bank=bank,
                    standalone_query=sq,
                    conversational_reply=cr
                )
            except Exception:
                pass

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

        # Check Greetings
        greetings = ["hi", "hello", "hey", "good morning", "good evening", "who are you", "what can you do", "help"]
        if any(lower == g or lower.startswith(g + " ") for g in greetings) and not any(w in lower for w in ["balance", "spend", "transaction", "bank", "account", "row", "record"]):
            sample_bank = canonical_banks[0] if canonical_banks else "HDFC BANK LIMITED"
            reply = (
                "Hello! How can I assist you with your banking and financial operations today?\n\n"
                "You can ask me about:\n"
                f"• **Available Balances**: *'What is our total available balance across all banks?'*\n"
                f"• **Bank Accounts**: *'How many accounts do we have under {sample_bank}?'*\n"
                "• **Transaction Volumes**: *'How much was credited vs debited in June 2026?'*\n"
                "• **Reference ID Lookup**: *'Lookup transaction reference 1715499972'*."
            )
            return ConversationResolution(
                intent="GREETING",
                context_scope="GLOBAL",
                resolved_bank=None,
                standalone_query=query,
                conversational_reply=reply
            )

        # Check Affirmations after clarification
        last_asst = history[-1]["content"] if history and history[-1].get("role") == "assistant" else ""
        is_affirmation = any(lower == a or lower.startswith(a + " ") for a in [
            "yes", "yep", "yeah", "yup", "correct", "right", "yes you are right",
            "you are right", "that's right", "thats right", "sure", "confirm", "confirmed",
            "proceed", "go ahead", "ok", "okay", "please", "yes please"
        ])

        if is_affirmation and "Did you mean" in last_asst:
            # Extract suggested bank from assistant message
            for b in canonical_banks:
                if b.lower() in last_asst.lower():
                    prev_user_q = history[-2]["content"] if len(history) >= 2 and history[-2].get("role") == "user" else f"Show balance for {b}"
                    sq = re.sub(r"\b(hdfc|sbi|icici|axis|kotak|canara|aubl)\b", b, prev_user_q, flags=re.IGNORECASE)
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

        # Out-of-scope check
        if any(w in lower for w in ["weather", "joke", "poem", "recipe", "capital of", "president", "movie"]):
            v1 = canonical_banks[0] if canonical_banks else "HDFC BANK LIMITED"
            reply = (
                "I am specifically designed to assist with **company financial & banking operations** "
                "(bank accounts, available balances, transaction tracking, credit/debit breakdowns, and reference searches).\n\n"
                "I cannot assist with general knowledge or unrelated topics. Please ask a question related to your financial datasets, for example:\n"
                "• **'What is our total available balance across all banks?'**\n"
                "• **'How much was credited vs debited in June 2026?'**\n"
                f"• **'What is our balance at {v1}?'**\n"
                "• **'Lookup transaction reference 1715499972'**"
            )
            return ConversationResolution(
                intent="OUT_OF_SCOPE",
                context_scope="GLOBAL",
                resolved_bank=None,
                standalone_query=query,
                conversational_reply=reply
            )

        return ConversationResolution(
            intent="FINANCIAL",
            context_scope="GLOBAL",
            resolved_bank=None,
            standalone_query=query,
            conversational_reply=None
        )

conversation_agent = ConversationContextAgent()
