from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

from reasoning_app.runner import run_reasoning


@csrf_exempt
def reasoning_test_view(request):
    """
    Test endpoint for reasoning layer
    POST: {"text": "your question"}
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            text = data.get("text", "")
            
            if not text:
                return JsonResponse({"error": "No text provided"}, status=400)
            
            state = run_reasoning(text)
            
            return JsonResponse({
                "text": text,
                "question_type": state.get("question_type"),
                "needs_sql": state.get("needs_sql"),
                "needs_chart": state.get("needs_chart"),
                "error": state.get("error")
            })
        
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    
    return JsonResponse({"error": "Only POST allowed"}, status=405)

