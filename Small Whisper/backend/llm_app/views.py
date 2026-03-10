import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from shared.pipeline import process_question


@csrf_exempt
def intent_test_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    question = (data.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "No question provided"}, status=400)

    result = process_question(question)
    if result.get("error"):
        return JsonResponse(result, status=422)
    return JsonResponse(result)
