# Transformation Rules DSL (Implemented)

This document describes the YAML format used by the transformer service to load transformation rules via `shared/models/rule_yaml_parser.py`.

## File Structure

```yaml
transformation_rules:
  - rule_id: "trim_strings_v1"
    rule_type: "CLEAN"
    priority: 1
    description: "Trim whitespace from all string fields"
    condition:
      type: "always"
    action:
      type: "trim_strings"
```

Required fields:
- `rule_id` (string)
- `rule_type` (enum: `CLEAN`, `VALIDATE`, `TRANSFORM`, `ENRICH`)
- `priority` (integer, >= 0)
- `condition` (object)
- `action` (object)

Optional metadata:
- `description`, `version`, `author`, plus any extra keys

## Conditions (Supported)

Condition `type` values:
- `always`
- `field_exists` (`field_name`)
- `field_not_exists` (`field_name`)
- `field_is_null` (`field_name`)
- `field_is_not_null` (`field_name`)
- `field_type` (`field_name`, `expected_type`)
- `field_value_equals` (`field_name`, `expected_value`)
- `field_value_in` (`field_name`, `allowed_values`)
- `field_value_matches` (`field_name`, `pattern`)
- `field_value_contains` (`field_name`, `substring`)
- `field_value_range` (`field_name`, `min_value`/`max_value`)
- `all_fields_exist` (`field_names`)
- `any_field_exists` (`field_names`)
- `and` (`conditions`)
- `or` (`conditions`)
- `not` (`condition`)

`expected_type` values map to Python types: `string`, `integer`, `float`, `boolean`, `list`, `dict`.

## Actions (Supported)

Action `type` values:
- `trim_strings`
- `trim_field` (`field_name`)
- `uppercase_strings`
- `uppercase_field` (`field_name`)
- `lowercase_strings`
- `lowercase_field` (`field_name`)
- `normalize_whitespace`
- `normalize_whitespace_field` (`field_name`)
- `cast_to_int` (`field_name`, `on_error`)
- `cast_to_float` (`field_name`, `on_error`)
- `cast_to_bool` (`field_name`, `on_error`)
- `cast_to_date` (`field_name`, `date_format`, `on_error`)
- `regex_replace` (`field_name`, `pattern`, `replacement`, `flags`)
- `regex_extract` (`field_name`, `pattern`, `group`, `on_no_match`)
- `remove_field` (`field_name`)
- `remove_null_fields`
- `rename_field` (`old_name`, `new_name`)
- `copy_field` (`source_name`, `dest_name`)
- `replace_value` (`field_name`, `old_value`, `new_value`)
- `default_value` (`field_name`, `default`)
- `compose` (`actions`)

`on_error` handling is implemented by action functions and may include behaviors like raising or skipping.

## Example: Validations + Transformations

```yaml
transformation_rules:
  - rule_id: "trim_v1"
    rule_type: "CLEAN"
    priority: 1
    condition:
      type: "always"
    action:
      type: "trim_strings"

  - rule_id: "email_regex_v1"
    rule_type: "VALIDATE"
    priority: 10
    condition:
      type: "field_value_matches"
      field_name: "email"
      pattern: "^[^@]+@[^@]+\\.[^@]+$"
    action:
      type: "copy_field"
      source_name: "email"
      dest_name: "email"
```

## Loading Rules

Rules are loaded by the transformer when `TRANSFORMER_RULES_PATH` is set:

```
TRANSFORMER_RULES_PATH=/app/rules/cleaning_rules.yaml
```

If parsing fails, the transformer logs warnings and continues with no rules.
