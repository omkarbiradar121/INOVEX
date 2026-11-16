from celery import shared_task
from .models import Manual
from .rag_engine import index_manual

@shared_task
def index_manual_task(manual_id):
    """
    Celery background task to extract PDF text, chunk, embed, and store in database.
    """
    try:
        manual = Manual.objects.get(id=manual_id)
        count = index_manual(manual)
        return {'status': 'success', 'manual_id': manual_id, 'chunks_created': count}
    except Manual.DoesNotExist:
        return {'status': 'error', 'message': f'Manual {manual_id} does not exist'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
