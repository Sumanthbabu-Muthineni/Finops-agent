from backend.core.models import ConfidenceBreakdown

class ConfidenceEvaluator:
    def __init__(self, w_entity: float = 0.4, w_ast: float = 0.3, w_data: float = 0.3):
        self.w_entity = w_entity
        self.w_ast = w_ast
        self.w_data = w_data

    def evaluate(
        self,
        entity_score: float,
        ast_valid: bool,
        row_count: int,
        resolved_vendor: str = None
    ) -> ConfidenceBreakdown:
        """
        Calculates mathematical confidence score:
        C = w_entity * S_entity + w_ast * S_ast + w_data * S_data
        """
        # 1. Entity Score
        s_entity = max(0.0, min(1.0, entity_score))

        # 2. AST Score
        s_ast = 1.0 if ast_valid else 0.0

        # 3. Data Score (MySQL grounded reality)
        if row_count > 0:
            s_data = 1.0
        else:
            s_data = 0.0

        # Compute weighted sum
        score = (self.w_entity * s_entity) + (self.w_ast * s_ast) + (self.w_data * s_data)
        score = round(score, 2)

        # Determine Tier
        if score >= 0.85 and row_count > 0:
            tier = "HIGH"
            explanation = (
                f"High confidence ({int(score*100)}%): "
                f"Entity matched ({int(s_entity*100)}%), valid query structure, "
                f"and {row_count} records retrieved from MySQL database."
            )
        elif score >= 0.65 and row_count > 0:
            tier = "MEDIUM"
            explanation = (
                f"Medium confidence ({int(score*100)}%): "
                f"Query matched entity '{resolved_vendor}' ({int(s_entity*100)}%), "
                f"returning {row_count} records."
            )
        else:
            tier = "LOW"
            if row_count == 0:
                explanation = "Low confidence: 0 matching records found in database."
            else:
                explanation = "Low confidence: Entity could not be resolved or query parameters were ambiguous."

        return ConfidenceBreakdown(
            score=score,
            tier=tier,
            entity_score=round(s_entity, 2),
            ast_score=round(s_ast, 2),
            data_score=round(s_data, 2),
            explanation=explanation
        )

confidence_evaluator = ConfidenceEvaluator()
