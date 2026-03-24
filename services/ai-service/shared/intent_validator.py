"""
Multi-Pass Intent & SQL Validation System

Implements three validation passes:
1. Intent Validation - Semantic alignment between question and intent
2. Schema & Type Validation - Column existence and type compatibility
3. SQL Executability Validation - Syntax and runtime safety

STRICT MODE: Enforces correctness over convenience.
Refuses to generate misleading SQL with generic fallbacks.
"""


def _identify_question_domain(question_lower: str) -> str | None:
    """
    Identify the domain/topic of the question for semantic matching.
    Returns: 'academic', 'financial', 'sales', 'customer', etc. or None
    """
    domains = {
        "academic": ["score", "grade", "student", "test", "exam", "math", "english", "reading", "subject", "course", "education", "school"],
        "financial": ["revenue", "profit", "cost", "price", "sales", "payment", "amount", "balance", "expenditure", "budget", "fee"],
        "sales": ["order", "product", "customer", "quantity", "sold", "purchase"],
        "customer": ["customer", "user", "client", "member", "account"],
        "temporal": ["year", "month", "day", "date", "time", "period"],
        "enrollment": ["enroll", "enrollment", "student", "grades", "population"],
    }
    
    for domain, keywords in domains.items():
        if any(kw in question_lower for kw in keywords):
            return domain
    
    return None


def _identify_column_domain(col_lower: str) -> str | None:
    """
    Identify the domain of a column based on its name.
    """
    domains = {
        "academic": ["score", "grade", "gpa", "test", "exam", "subject", "mark", "reading", "math", "english"],
        "financial": ["revenue", "profit", "cost", "price", "amount", "balance", "salary", "fee", "expenditure", "outlay"],
        "sales": ["order", "product", "quantity", "qty", "sold", "purchase"],
        "customer": ["customer", "user", "client", "member", "account"],
        "temporal": ["year", "month", "day", "date", "time", "created", "updated"],
        "enrollment": ["enroll", "grades", "student", "population"],
    }
    
    for domain, keywords in domains.items():
        if any(kw in col_lower for kw in keywords):
            return domain
    
    return None


def _extract_metric_intent(question_lower: str) -> list[str]:
    """
    🔴 STEP 2: Extract metric-specific semantic intent from question.
    
    Examples:
    - "math scores" → ["math"]
    - "reading and english scores" → ["reading", "english"]
    - "enrollment count" → ["enroll", "enrollment"]
    - "total expenditure" → ["expenditure", "expense", "spending"]
    
    Returns list of metric intent keywords.
    """
    metric_intents = []
    
    # Academic sub-domains
    if "math" in question_lower:
        metric_intents.append("math")
    if "reading" in question_lower:
        metric_intents.append("reading")
    if "english" in question_lower:
        metric_intents.append("english")
    if "science" in question_lower:
        metric_intents.append("science")
    if "gpa" in question_lower:
        metric_intents.append("gpa")
    
    # Financial sub-domains
    if any(kw in question_lower for kw in ["revenue", "income", "sales"]):
        metric_intents.append("revenue")
    if any(kw in question_lower for kw in ["expenditure", "expense", "spending", "cost"]):
        metric_intents.append("expenditure")
    if "profit" in question_lower:
        metric_intents.append("profit")
    if "fee" in question_lower or "tuition" in question_lower:
        metric_intents.append("fee")
    
    # Demographic sub-domains
    if any(kw in question_lower for kw in ["enroll", "enrollment"]):
        metric_intents.append("enrollment")
    if "population" in question_lower or "headcount" in question_lower:
        metric_intents.append("population")
    
    return metric_intents


def _calculate_semantic_score(column_name: str, metric_intents: list[str], question_tokens: set) -> int:
    """
    🔴 STEP 4: Calculate semantic relevance score for intra-domain metric matching.
    
    Args:
        column_name: The column name to score
        metric_intents: Extracted metric intents from question (e.g., ["math"])
        question_tokens: Set of tokens from question
    
    Returns:
        Semantic score (higher = better match)
    """
    score = 0
    col_lower = column_name.lower()
    col_tokens = set(col_lower.replace("_", " ").split())
    
    # 🔴 CRITICAL: Exact metric intent match (highest priority)
    for intent in metric_intents:
        if intent in col_lower:
            score += 50  # Very high score for explicit match
    
    # Token overlap with question
    overlap = col_tokens & question_tokens
    score += len(overlap) * 10
    
    # Substring match
    if any(intent in col_lower for intent in metric_intents):
        score += 20
    
    # Penalize if column name suggests a different sub-domain
    # (e.g., "reading_score" for "math score" question)
    conflicting_metrics = ["math", "reading", "english", "science", "revenue", "expenditure", "profit"]
    for conflicting in conflicting_metrics:
        if conflicting in col_lower and conflicting not in metric_intents:
            score -= 100  # Severe penalty for intra-domain semantic mismatch
    
    return score


def validate_intent_semantics(intent: dict, question: str, schema: dict) -> dict:
    """
    Pass 1: Domain & Intent Validation with Intra-Domain Semantic Resolution
    
    Validates that extracted intent semantically matches the question.
    
    🔴 SEMANTIC-FIRST PRINCIPLE (ENHANCED):
    1. Identify question domain FIRST (domain lock)
    2. Extract metric-specific intent (e.g., "math" within academic domain)
    3. Check intra-domain semantic alignment (prevent "reading" for "math" questions)
    4. Reject cross-domain substitutions
    5. Type issues are NOT checked here (handled in Pass 2)
    
    Returns validation result with issues flagged.
    """
    issues = []
    warnings = []
    
    table = intent.get("table")
    metrics = intent.get("metrics", [])
    dimensions = intent.get("dimensions", [])
    
    # Validate table exists
    if table not in schema:
        issues.append(f"Table '{table}' not found in schema")
        return {"valid": False, "issues": issues, "warnings": warnings}
    
    question_lower = question.lower()
    question_tokens = set(question_lower.split())
    
    # 🔴 STEP 1: Identify question domain (LOCK THE DOMAIN)
    question_domain = _identify_question_domain(question_lower)
    
    if not question_domain:
        warnings.append("Could not identify clear question domain")
    else:
        print(f"🔒 Domain locked: {question_domain.upper()}")
    
    # 🔴 STEP 2: Extract metric-specific intent
    metric_intents = _extract_metric_intent(question_lower)
    if metric_intents:
        print(f"🎯 Metric intent(s): {', '.join(metric_intents).upper()}")
    
    # 🔴 STRICT: Check for generic fallback usage (NOT ALLOWED)
    for metric in metrics:
        if metric.get("_semantic_fallback"):
            issues.append(
                "❌ DOMAIN VIOLATION: Generic fallback metric used. "
                "Domain-specific metric required."
            )
            return {"valid": False, "issues": issues, "warnings": warnings}
    
    # ⚠️ Check for auto-repaired metrics (reduce confidence but allow)
    has_auto_repair = False
    has_weak_match = False
    for metric in metrics:
        if metric.get("_auto_repaired"):
            has_auto_repair = True
            if metric.get("_weak_match"):
                has_weak_match = True
                warnings.append(
                    f"Auto-repaired metric '{metric['column']}' has weak semantic alignment"
                )
    
    # Check if metrics align with question intent
    for metric in metrics:
        col = metric.get("column")
        agg = metric.get("aggregation")
        
        # Skip wildcard columns (COUNT(*)) - 🔴 SHOULD NOT EXIST in strict mode
        if col == "*":
            # Only allow COUNT(*) if no domain-specific alternative exists
            if question_domain in ["academic", "financial", "sales"]:
                issues.append(
                    f"❌ DOMAIN VIOLATION: Generic COUNT(*) used for {question_domain} question. "
                    f"Domain-specific metric required."
                )
                return {"valid": False, "issues": issues, "warnings": warnings}
            else:
                warnings.append("COUNT(*) used - no domain-specific alternative found")
        
        # 🔴 STEP 3: Check domain alignment (INTER-DOMAIN validation)
        column_domain = _identify_column_domain(col.lower())
        
        if question_domain and column_domain:
            if question_domain != column_domain:
                # 🔴 CRITICAL DOMAIN VIOLATION - REFUSE
                issues.append(
                    f"❌ DOMAIN VIOLATION: Metric '{col}' ({column_domain} domain) "
                    f"cannot be used for {question_domain} question. "
                    f"This violates semantic correctness."
                )
                return {"valid": False, "issues": issues, "warnings": warnings}
        
        # 🔴 STEP 4: Check INTRA-DOMAIN semantic alignment (NEW - CRITICAL)
        if metric_intents:
            semantic_score = _calculate_semantic_score(col, metric_intents, question_tokens)
            
            # If score is negative, it means there's a conflicting metric
            if semantic_score < 0:
                issues.append(
                    f"❌ INTRA-DOMAIN SEMANTIC MISMATCH: Metric '{col}' does not match "
                    f"the specific metric intent '{', '.join(metric_intents)}' in question. "
                    f"Same domain but different semantic meaning."
                )
                return {"valid": False, "issues": issues, "warnings": warnings}
            
            # Warn if score is low (weak semantic match)
            if semantic_score < 10 and not metric.get("_auto_repaired"):
                warnings.append(
                    f"Weak intra-domain semantic match: '{col}' has low relevance "
                    f"to metric intent '{', '.join(metric_intents)}'"
                )
        
        # Check general semantic alignment (token overlap)
        col_tokens = set(col.lower().replace("_", " ").split())
        overlap = col_tokens & question_tokens
        
        # 🔴 STRICT: Require semantic alignment within the domain
        if not overlap and len(col_tokens) > 0 and not metric_intents:
            # Only check general alignment if no specific metric intents were extracted
            semantic_match = any(
                token in question_lower for token in col_tokens if len(token) > 3
            )
            if not semantic_match and not metric.get("_auto_repaired"):
                warnings.append(
                    f"Weak semantic alignment: Metric column '{col}' not clearly "
                    f"referenced in question"
                )
    
    # Validate dimensions match grouping intent
    grouping_keywords = ["by", "per", "each", "grouped", "breakdown", "across"]
    has_grouping_intent = any(kw in question_lower for kw in grouping_keywords)
    
    if has_grouping_intent and not dimensions:
        warnings.append("Question implies grouping but no dimensions extracted")
    
    if dimensions and not has_grouping_intent:
        warnings.append("Dimensions extracted but question may not imply grouping")
    
    # Check dimension semantic alignment
    for dim in dimensions:
        dim_tokens = set(dim.lower().replace("_", " ").split())
        question_tokens = set(question_lower.split())
        
        overlap = dim_tokens & question_tokens
        if not overlap:
            warnings.append(f"Dimension '{dim}' may not align with question")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings
    }


def validate_schema_and_types(intent: dict, schema: dict) -> dict:
    """
    Pass 2: Schema & Type Validation with Type Repair
    
    🔧 TYPE REPAIR PASS (DOMAIN-FIRST PRINCIPLE):
    - Column existence is validated
    - Type mismatches are identified
    - Type casting recommendations are generated
    - Domain-aligned columns are PRESERVED even if type-incompatible
    - Type issues are considered REPAIRABLE, not FATAL
    
    Returns validation result with type casting recommendations.
    """
    issues = []
    type_casting_needed = []
    
    table = intent.get("table")
    if table not in schema:
        issues.append(f"Table '{table}' not found")
        return {"valid": False, "issues": issues, "type_casting": []}
    
    columns = schema[table]
    column_map = {c["name"]: c for c in columns}
    
    # Validate metrics
    for metric in intent.get("metrics", []):
        col = metric.get("column")
        agg = metric.get("aggregation")
        
        # Skip wildcard
        if col == "*":
            continue
        
        # Check column exists
        if col not in column_map:
            issues.append(f"Metric column '{col}' not found in table '{table}'")
            continue
        
        col_type = column_map[col].get("type", "")
        
        # 🔧 TYPE REPAIR: Check if numeric aggregation on STRING column
        if agg in {"AVG", "SUM", "MIN", "MAX"}:
            if _is_string_type(col_type):
                # 🔴 DOMAIN-FIRST: Don't reject, add to type_casting list
                type_casting_needed.append({
                    "column": col,
                    "current_type": col_type,
                    "aggregation": agg,
                    "required_cast": _infer_target_cast(col_type, col)
                })
                print(f"🔧 Type repair scheduled: {col} ({col_type}) → {_infer_target_cast(col_type, col)}")
            elif not _is_numeric_type(col_type):
                # Only fail if type is truly incompatible (e.g., Date for AVG)
                # Try to cast anyway for maximum domain preservation
                type_casting_needed.append({
                    "column": col,
                    "current_type": col_type,
                    "aggregation": agg,
                    "required_cast": _infer_target_cast(col_type, col)
                })
                print(f"⚠️ Aggressive type repair: Attempting cast for {col} ({col_type})")
    
    # Validate dimensions
    for dim in intent.get("dimensions", []):
        if dim not in column_map:
            issues.append(f"Dimension column '{dim}' not found in table '{table}'")
    
    # Validate filters
    for filt in intent.get("filters", []):
        col = filt.get("column")
        if col and col not in column_map:
            issues.append(f"Filter column '{col}' not found in table '{table}'")
    
    # Validate order_by
    for order in intent.get("order_by", []):
        col = order.get("column")
        if col and col not in column_map:
            issues.append(f"Order by column '{col}' not found in table '{table}'")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "type_casting": type_casting_needed
    }


def validate_sql_executability(sql: str, intent: dict, schema: dict) -> dict:
    """
    Pass 3: SQL Executability Validation
    
    Validates SQL syntax and runtime safety.
    Returns validation result with recommendations.
    """
    issues = []
    warnings = []
    
    # Basic SQL structure validation
    sql_upper = sql.upper()
    
    # Check for required clauses
    if "SELECT" not in sql_upper:
        issues.append("Missing SELECT clause")
    
    if "FROM" not in sql_upper:
        issues.append("Missing FROM clause")
    
    # Check for potential type errors
    table = intent.get("table")
    if table in schema:
        columns = schema[table]
        column_map = {c["name"]: c for c in columns}
        
        for metric in intent.get("metrics", []):
            col = metric.get("column")
            agg = metric.get("aggregation")
            
            if col == "*":
                continue
            
            if col in column_map:
                col_type = column_map[col].get("type", "")
                
                # Check if aggregation on STRING without casting
                if agg in {"AVG", "SUM"} and _is_string_type(col_type):
                    # Check if SQL has explicit casting (both safe and unsafe versions)
                    # 🔒 NaN-SAFE: Also check for safe cast functions
                    has_cast = (
                        f"toFloat64({col})" in sql or f"toInt64({col})" in sql or
                        f"toFloat64OrNull({col})" in sql or f"toInt64OrNull({col})" in sql
                    )
                    if not has_cast:
                        issues.append(
                            f"Aggregation {agg} on STRING column '{col}' requires explicit type casting"
                        )
    
    # Check for GROUP BY when using aggregations with dimensions
    if intent.get("dimensions") and intent.get("metrics"):
        if "GROUP BY" not in sql_upper:
            issues.append("Aggregation with dimensions requires GROUP BY clause")
        else:
            # 🔴 CRITICAL: Validate GROUP BY has actual content (not empty)
            group_by_index = sql_upper.find("GROUP BY")
            if group_by_index >= 0:
                after_group_by = sql_upper[group_by_index + 8:].strip()
                # Check if GROUP BY is followed immediately by ORDER BY, LIMIT, or semicolon
                if after_group_by.startswith(("ORDER BY", "LIMIT", ";")):
                    issues.append("GROUP BY clause is empty - dimensions were filtered out but GROUP BY remains")
                # Check if GROUP BY has only whitespace or commas
                elif not after_group_by or after_group_by.startswith(",") or after_group_by.replace(",", "").strip() == "":
                    issues.append("GROUP BY clause is malformed - contains no valid columns")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings
    }


def _is_string_type(col_type: str) -> bool:
    """Check if column type is a string type."""
    if not col_type:
        return False
    return "string" in col_type.lower() or "char" in col_type.lower()


def _is_numeric_type(col_type: str) -> bool:
    """Check if column type is numeric."""
    if not col_type:
        return False
    
    col_type_lower = col_type.lower()
    numeric_types = ("int", "float", "decimal", "double", "numeric", "uint", "bigint", "smallint", "tinyint")
    return any(nt in col_type_lower for nt in numeric_types)


def _infer_target_cast(col_type: str, col_name: str) -> str:
    """
    Infer appropriate ClickHouse cast function based on column type and name.
    
    🔒 NaN-SAFE: Returns safe cast functions that return NULL instead of NaN.
    The SQL compiler will use these to generate NaN-safe SQL.
    """
    col_name_lower = col_name.lower()
    
    # If column name suggests it should be integer
    integer_keywords = ("id", "count", "num", "qty", "quantity", "year", "age")
    if any(kw in col_name_lower for kw in integer_keywords):
        return "toInt64OrNull"  # 🔒 Safe version returns NULL instead of throwing error
    
    # Default to float for numeric operations
    return "toFloat64OrNull"  # 🔒 Safe version returns NULL instead of NaN


def perform_multi_pass_validation(intent: dict, sql: str, question: str, schema: dict) -> dict:
    """
    Perform all three validation passes and return comprehensive results.
    
    Returns:
        {
            "valid": bool,
            "pass1": {...},  # Intent validation
            "pass2": {...},  # Schema & type validation
            "pass3": {...},  # SQL validation
            "overall_issues": [...],
            "overall_warnings": [...],
            "requires_reconstruction": bool
        }
    """
    # Pass 1: Intent Validation
    pass1 = validate_intent_semantics(intent, question, schema)
    
    # Pass 2: Schema & Type Validation
    pass2 = validate_schema_and_types(intent, schema)
    
    # Pass 3: SQL Executability Validation
    pass3 = validate_sql_executability(sql, intent, schema)
    
    # Aggregate results
    all_issues = []
    all_warnings = []
    
    if not pass1["valid"]:
        all_issues.extend([f"[Intent] {issue}" for issue in pass1["issues"]])
    all_warnings.extend([f"[Intent] {w}" for w in pass1["warnings"]])
    
    if not pass2["valid"]:
        all_issues.extend([f"[Schema] {issue}" for issue in pass2["issues"]])
    
    if not pass3["valid"]:
        all_issues.extend([f"[SQL] {issue}" for issue in pass3["issues"]])
    all_warnings.extend([f"[SQL] {w}" for w in pass3["warnings"]])
    
    # Determine if reconstruction is needed
    requires_reconstruction = len(all_issues) > 0 or len(pass2.get("type_casting", [])) > 0
    
    return {
        "valid": pass1["valid"] and pass2["valid"] and pass3["valid"],
        "pass1": pass1,
        "pass2": pass2,
        "pass3": pass3,
        "overall_issues": all_issues,
        "overall_warnings": all_warnings,
        "requires_reconstruction": requires_reconstruction,
        "type_casting_needed": pass2.get("type_casting", [])
    }

