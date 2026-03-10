#!/usr/bin/env python3
"""Fix unhashable type issue in schema_evolution.py"""

with open('schema_evolution.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and fix the problematic section
output_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # Look for the problematic line
    if 'unique_values = list(set(values))' in line and 'try:' not in lines[i-1]:
        # Add try block
        indent = ' ' * (len(line) - len(line.lstrip()))
        output_lines.append(f'{indent}# Only add enum constraint for hashable types\n')
        output_lines.append(f'{indent}try:\n')
        output_lines.append(f'{indent}    unique_values = list(set(values))\n')
        i += 1
        
        # Copy lines until we find the closing of the if block
        while i < len(lines):
            line = lines[i]
            if 'return constraints' in line:
                # Add except block before return
                output_lines.append(f'{indent}except TypeError:\n')
                output_lines.append(f'{indent}    # Skip enum constraint for unhashable types (lists, dicts)\n')
                output_lines.append(f'{indent}    pass\n')
                output_lines.append(line)
                break
            else:
                # Indent the constraint append lines
                if 'constraints.append' in line:
                    output_lines.append('    ' + line)
                else:
                    output_lines.append(line)
            i += 1
    else:
        output_lines.append(line)
    
    i += 1

with open('schema_evolution.py', 'w', encoding='utf-8') as f:
    f.writelines(output_lines)

print('Fixed unhashable type issue')
