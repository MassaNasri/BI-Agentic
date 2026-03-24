def _detect_aggregation_type(question_lower: str) -> str | None:
    """
    Detect aggregation type from question text.
    Returns: AVG, SUM, MAX, MIN, COUNT, or None
    """
    agg_patterns = [
        (["average", "avg", "mean"], "AVG"),
        (["sum", "total"], "SUM"),
        (["maximum", "max", "highest", "largest"], "MAX"),
        (["minimum", "min", "lowest", "smallest"], "MIN"),
        (["count", "number of", "how many"], "COUNT"),
    ]
    
    for keywords, agg_type in agg_patterns:
        if any(kw in question_lower for kw in keywords):
            return agg_type
    
    return None


def _is_numeric_type(col_type: str) -> bool:
    """
    Check if a column type is numeric based on ClickHouse type names.
    Covers: Int*, UInt*, Float*, Decimal*, Nullable variants, etc.
    """
    if not col_type:
        return False
    
    col_type_lower = col_type.lower()
    
    # Core numeric types
    numeric_types = ("int", "float", "decimal", "double", "numeric")
    if any(nt in col_type_lower for nt in numeric_types):
        return True
    
    # Specific ClickHouse types
    clickhouse_numeric = ("uint", "bigint", "smallint", "tinyint", "money", "real")
    if any(nt in col_type_lower for nt in clickhouse_numeric):
        return True
    
    return False


def _is_string_type(col_type: str) -> bool:
    """
    Check if a column type is a string type.
    Covers: String, VARCHAR, CHAR, TEXT, etc.
    """
    if not col_type:
        return False
    
    col_type_lower = col_type.lower()
    return "string" in col_type_lower or "char" in col_type_lower or "text" in col_type_lower


def _extract_metric_intent_sanitizer(question_lower: str) -> list[str]:
    """
    🔴 Extract metric-specific semantic intent from question (sanitizer version).
    
    Examples:
    - "math scores" → ["math"]
    - "reading scores" → ["reading"]
    - "enrollment" → ["enroll", "enrollment"]
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
    
    return metric_intents


def _calculate_intra_domain_score(col: str, metric_intents: list[str], question_tokens: set) -> int:
    """
    🔴 Calculate intra-domain semantic score for metric resolution.
    
    Prevents same-domain but semantically different metrics from being selected.
    """
    score = 0
    col_lower = col.lower()
    col_tokens = set(col_lower.replace("_", " ").split())
    
    # 🔴 CRITICAL: Exact metric intent match
    has_exact_match = False
    for intent in metric_intents:
        if intent in col_lower:
            score += 50  # Very high score
            has_exact_match = True
    
    # Token overlap
    overlap = col_tokens & question_tokens
    score += len(overlap) * 10
    
    # 🔴 PENALIZE conflicting metrics within same domain
    conflicting_metrics = ["math", "reading", "english", "science", "revenue", "expenditure", "profit", "enrollment"]
    has_conflict = False
    for conflicting in conflicting_metrics:
        if conflicting in col_lower and conflicting not in metric_intents and metric_intents:
            score -= 100  # Severe penalty for intra-domain mismatch
            has_conflict = True
    
    # 🔴 PENALIZE generic/aggregate columns when specific intent exists
    # If we have specific metric intents (e.g., "math") but column is generic (e.g., "total")
    if metric_intents and not has_exact_match and not has_conflict:
        generic_terms = ["total", "sum", "average", "overall", "combined", "aggregate"]
        if any(term in col_lower for term in generic_terms):
            score -= 30  # Penalty for generic when specific intent exists
    
    return score


def _infer_metric_from_question(question: str, numeric_columns: list, categorical_columns: list, schema_columns: list) -> dict | None:
    """
    Infer a metric from the question when sanitization removed all metrics.
    
    🔴 ENHANCED WITH INTRA-DOMAIN SEMANTIC RESOLUTION:
    - Domain-level matching (academic, financial, etc.)
    - Metric-level matching (math vs reading within academic)
    - Prevents same-domain but semantically wrong metrics
    
    Args:
        question: The user's question
        numeric_columns: List of numeric column names
        categorical_columns: List of categorical column names
        schema_columns: Full column info with types for better matching
    """
    question_lower = question.lower()
    question_tokens = set(question_lower.split())
    
    # Map common question patterns to aggregation types
    agg_patterns = [
        (["average", "avg", "mean"], "AVG"),
        (["sum", "total"], "SUM"),
        (["maximum", "max", "highest", "largest"], "MAX"),
        (["minimum", "min", "lowest", "smallest"], "MIN"),
        (["count", "number of", "how many"], "COUNT"),
    ]
    
    # Find which aggregation is implied
    detected_agg = None
    for keywords, agg_type in agg_patterns:
        if any(kw in question_lower for kw in keywords):
            detected_agg = agg_type
            break
    
    if not detected_agg:
        return None
    
    # For COUNT, we can use any column or *
    if detected_agg == "COUNT":
        if numeric_columns:
            return {
                "column": numeric_columns[0],
                "aggregation": "COUNT",
                "alias": f"count_{numeric_columns[0]}"
            }
        return {
            "column": "*",
            "aggregation": "COUNT",
            "alias": "count"
        }
    
    # 🔴 STEP 1: Identify question domain (domain lock)
    question_domain = _identify_question_domain(question_lower)
    
    # 🔴 STEP 2: Extract metric-specific intent
    metric_intents = _extract_metric_intent_sanitizer(question_lower)
    
    # 🔴 STEP 3 & 4: Intra-domain metric matching with semantic scoring
    best_match = None
    best_score = -1000  # Start with very low score
    
    for col in numeric_columns:
        col_lower = col.lower()
        col_tokens = set(col_lower.replace("_", " ").split())
        
        # Base score from token overlap
        score = len(col_tokens & question_tokens)
        
        # Domain-level matching
        col_domain = _identify_column_domain(col_lower)
        if col_domain and col_domain == question_domain:
            score += 10  # Domain match bonus
        elif col_domain and question_domain and col_domain != question_domain:
            score -= 20  # Cross-domain penalty
        
        # 🔴 INTRA-DOMAIN semantic matching (CRITICAL - NEW)
        if metric_intents:
            intra_score = _calculate_intra_domain_score(col, metric_intents, question_tokens)
            score += intra_score
        
        # Substring match bonus
        if col_lower in question_lower or any(token in question_lower for token in col_tokens if len(token) > 3):
            score += 2
        
        # ID column penalty
        if "_id" in col_lower and "id" not in question_lower:
            score -= 3
        
        if score > best_score:
            best_score = score
            best_match = col
    
    # ✅ Only use inferred column if score is high enough and positive
    # Reject if intra-domain mismatch (negative score)
    if best_match and best_score >= 2:
        return {
            "column": best_match,
            "aggregation": detected_agg,
            "alias": f"{detected_agg.lower()}_{best_match}"
        }
    
    # If no good match found, return None
    return None


def _identify_question_domain(question_lower: str) -> str | None:
    """
    Identify the domain/topic of the question for semantic matching.
    Returns: 'academic', 'financial', 'sales', 'customer', etc. or None
    """
    domains = {
        "academic": ["score", "grade", "student", "test", "exam", "math", "english", "subject", "course"],
        "financial": ["revenue", "profit", "cost", "price", "sales", "payment", "amount", "balance"],
        "sales": ["order", "product", "customer", "quantity", "sold", "purchase"],
        "customer": ["customer", "user", "client", "member", "account"],
        "temporal": ["year", "month", "day", "date", "time", "period"],
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
        "academic": ["score", "grade", "gpa", "test", "exam", "subject", "mark"],
        "financial": ["revenue", "profit", "cost", "price", "amount", "balance", "salary", "fee"],
        "sales": ["order", "product", "quantity", "qty", "sold", "purchase"],
        "customer": ["customer", "user", "client", "member", "account"],
        "temporal": ["year", "month", "day", "date", "time", "created", "updated"],
    }
    
    for domain, keywords in domains.items():
        if any(kw in col_lower for kw in keywords):
            return domain
    
    return None


def resolve_entity_dimension(question: str, schema: dict, table: str):
    """
    Resolve linguistic entities (e.g. customer, product, user)
    to identifier columns in a generic way.
    """
    question = question.lower()
    columns = schema[table]  # list of dicts: {"name", "type"}

    identifier_columns = [
        c["name"] for c in columns
        if c["name"].endswith("_id") or c["name"].endswith("_name")
    ]

    for col in identifier_columns:
        base = col.replace("_id", "").replace("_name", "")
        if base in question:
            return col

    return None


def sanitize_intent(intent: dict, schema: dict, question: str) -> dict:
    """
    Dataset-agnostic and question-agnostic intent sanitizer.
    Removes only technically invalid or hallucinated parts.
    """

    table = intent.get("table")
    if table not in schema:
        raise ValueError("Invalid table in intent")

    columns = schema[table]  # list of dicts
    column_names = [c["name"] for c in columns]

    numeric_like_keywords = (
        "id", "count", "num", "amount", "price", "total", "sales", "qty"
    )

    # ✅ Also check for actual numeric types from schema
    numeric_columns = [
        c["name"] for c in columns
        if any(k in c["name"].lower() for k in numeric_like_keywords)
        or _is_numeric_type(c.get("type", ""))
    ]

    categorical_columns = [
        c for c in column_names if c not in numeric_columns
    ]

    # ---------------- Metrics ----------------
    sanitized_metrics = []
    for m in intent.get("metrics", []):
        col = m.get("column")
        agg = m.get("aggregation")
        alias = m.get("alias")

        if not col or not agg:
            continue
        if col not in column_names:
            continue
        if agg in {"SUM", "AVG", "MIN", "MAX"} and col not in numeric_columns:
            continue

        sanitized_metrics.append({
            "column": col,
            "aggregation": agg,
            "alias": alias or f"{agg.lower()}_{col}"
        })

    # 🔧 AUTO-REPAIR: Try semantic inference with STRICT domain awareness
    if not sanitized_metrics:
        print("⚠️ No valid metrics after sanitization. Attempting DOMAIN-PRESERVING AUTO-REPAIR...")
        
        # 🔒 STEP 1: LOCK THE DOMAIN
        question_domain = _identify_question_domain(question.lower())
        if question_domain:
            print(f"🔒 Domain locked: {question_domain.upper()}")
        else:
            print("⚠️ Could not identify clear question domain")
        
        # Strategy 1: Infer from question with domain matching
        inferred_metric = _infer_metric_from_question(
            question, numeric_columns, categorical_columns, columns
        )
        
        if inferred_metric:
            sanitized_metrics.append(inferred_metric)
            print(f"✅ AUTO-REPAIR successful: Inferred metric {inferred_metric}")
        else:
            # Strategy 2: Find domain-aligned column (STRICT - stay within domain)
            print("⚠️ Standard inference failed. Attempting STRICT domain-preserving resolution...")
            
            if question_domain:
                # 🔴 DOMAIN-FIRST: Find ALL columns in the question domain
                # INCLUDING string-typed columns (type repair happens later)
                domain_columns = []
                for col_info in columns:
                    col_name = col_info["name"]
                    col_type = col_info.get("type", "")
                    col_domain = _identify_column_domain(col_name.lower())
                    
                    if col_domain == question_domain:
                        domain_columns.append({
                            "name": col_name,
                            "type": col_type,
                            "is_numeric": _is_numeric_type(col_type),
                            "is_string": _is_string_type(col_type)
                        })
                
                if domain_columns:
                    # 🔴 NEW: Apply intra-domain semantic scoring
                    metric_intents = _extract_metric_intent_sanitizer(question.lower())
                    question_tokens = set(question.lower().split())
                    
                    best_col = None
                    best_score = -1000
                    best_col_info = None
                    
                    for col_info in domain_columns:
                        col_name = col_info["name"]
                        
                        # Calculate intra-domain semantic score
                        score = _calculate_intra_domain_score(col_name, metric_intents, question_tokens)
                        
                        # Prefer numeric columns (small bonus)
                        if col_info["is_numeric"]:
                            score += 5
                        
                        if score > best_score:
                            best_score = score
                            best_col = col_name
                            best_col_info = col_info
                    
                    # Only use if score is reasonable (not heavily penalized)
                    if best_score > 0 or not metric_intents:
                        selected_col = best_col
                        requires_type_cast = best_col_info["is_string"]
                        
                        if best_col_info["is_numeric"]:
                            print(f"✅ Found numeric domain-aligned column: {selected_col} (score: {best_score})")
                        elif best_col_info["is_string"]:
                            print(f"🔧 Found string-typed domain-aligned column: {selected_col} (score: {best_score})")
                            print(f"   Type casting will be applied in Pass 2")
                        
                        # Detect aggregation type from question
                        detected_agg = _detect_aggregation_type(question.lower())
                        
                        metric_entry = {
                            "column": selected_col,
                            "aggregation": detected_agg or "AVG",
                            "alias": f"{(detected_agg or 'avg').lower()}_{selected_col}",
                            "_auto_repaired": True
                        }
                        
                        # Flag if type casting is needed (will be handled in validation)
                        if requires_type_cast:
                            metric_entry["_needs_type_cast"] = True
                        
                        sanitized_metrics.append(metric_entry)
                        print(f"✅ AUTO-REPAIR: Domain-preserving resolution successful")
                        print(f"   Domain: {question_domain}, Column: {selected_col}, Aggregation: {detected_agg or 'AVG'}")
                    else:
                        # All domain-aligned columns have negative scores (intra-domain mismatch)
                        print(f"❌ AUTO-REPAIR failed: Domain-aligned columns found, but none match metric intent {metric_intents}")
                        print(f"🔴 REFUSING intra-domain semantic mismatch")
                        
                        raise ValueError(
                            f"Semantic alignment failure: Found {question_domain} columns, but none match "
                            f"the specific metric intent '{', '.join(metric_intents)}'. "
                            f"Please clarify which specific metric to analyze."
                        )
                else:
                    # 🔴 NO DOMAIN-ALIGNED COLUMNS FOUND - REFUSE
                    print(f"❌ AUTO-REPAIR failed: No {question_domain} columns found in schema.")
                    print(f"🔴 REFUSING to use cross-domain substitution (domain locking enforced)")
                    
                    # List available columns in that domain
                    raise ValueError(
                        f"Semantic alignment failure: No {question_domain} metrics found in table. "
                        f"Cannot generate domain-correct query. "
                        f"Please verify that the table contains {question_domain}-related columns, "
                        f"or clarify which metric to analyze."
                    )
            else:
                # No clear domain detected - be more permissive but still prefer semantic matches
                print("⚠️ No clear domain detected. Attempting general semantic matching...")
                
                # Check for any score/metric columns regardless of exact match
                metric_like_columns = [
                    col for col in numeric_columns
                    if any(kw in col.lower() for kw in ["score", "avg", "total", "sum", "count", "revenue", "amount", "value"])
                ]
                
                if metric_like_columns:
                    detected_agg = _detect_aggregation_type(question.lower()) or "AVG"
                    selected_col = metric_like_columns[0]
                    
                    sanitized_metrics.append({
                        "column": selected_col,
                        "aggregation": detected_agg,
                        "alias": f"{detected_agg.lower()}_{selected_col}",
                        "_auto_repaired": True,
                        "_weak_match": True
                    })
                    print(f"⚠️ AUTO-REPAIR: Weak match used '{selected_col}' (low confidence)")
                else:
                    # 🔴 LAST RESORT: Request clarification
                    print("❌ AUTO-REPAIR failed: No semantically relevant metrics found.")
                    raise ValueError(
                        "Semantic alignment failure: Could not identify relevant metrics. "
                        "Please clarify which metric to analyze. "
                        f"Available columns: {', '.join(numeric_columns[:10])}..."
                    )

    intent["metrics"] = sanitized_metrics

    # ---------------- Dimensions ----------------
    sanitized_dimensions = [
        d for d in intent.get("dimensions", []) if d in categorical_columns
    ]

    if not sanitized_dimensions:
        resolved = resolve_entity_dimension(question, schema, table)
        if resolved:
            sanitized_dimensions = [resolved]

    intent["dimensions"] = sanitized_dimensions

    # ---------------- Filters ----------------
    question_lc = question.lower()
    sanitized_filters = []

    for f in intent.get("filters", []):
        col = f.get("column")
        op = f.get("operator")
        val = f.get("value")

        # Guard: لا نسمح بفلترة لم تُذكر قيمتها في السؤال
        if (
            col in column_names
            and op
            and val is not None
            and str(val).lower() in question_lc
        ):
            sanitized_filters.append({
                "column": col,
                "operator": op,
                "value": val
            })

    intent["filters"] = sanitized_filters

    # ---------------- Order By ----------------
    intent["order_by"] = [
        o for o in intent.get("order_by", [])
        if o.get("column") in column_names
        and o.get("direction", "ASC") in {"ASC", "DESC"}
    ]

    # ---------------- Limit ----------------
    limit = intent.get("limit")
    intent["limit"] = limit if isinstance(limit, int) and limit > 0 else None

    return intent
