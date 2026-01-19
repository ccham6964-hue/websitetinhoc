import os
import re
import google.generativeai as genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("  CẢNH BÁO: Thiếu GEMINI_API_KEY trong file .env")


def remove_markdown_formatting(text):
    """
    Loại bỏ các ký tự định dạng Markdown
    """
    # Loại bỏ headers (#, ##, ###)
    text = re.sub(r'#+\s*', '', text)
    
    # Loại bỏ bold/italic (**text**, *text*, __text__, _text_)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    
    # Loại bỏ code blocks (```code```)
    text = re.sub(r'```[\w]*\n?', '', text)
    text = re.sub(r'```', '', text)
    
    # Loại bỏ inline code (`code`)
    text = re.sub(r'`(.+?)`', r'\1', text)
    
    return text.strip()


def chat_with_gemini(user_message):
    if not GEMINI_API_KEY:
        return "Xin lỗi, dịch vụ AI chưa được cấu hình. Vui lòng liên hệ quản trị viên để bổ sung GEMINI_API_KEY."
    
    try:
        model = genai.GenerativeModel(
            'gemini-2.5-flash',
            generation_config={
                'temperature': 0.7,
                'top_p': 0.95,
                'top_k': 40,
                'max_output_tokens': 2048,
            }
            # ← XÓA system_instruction
        )
        
        # Nhúng system instruction vào prompt
        full_prompt = f"""Bạn là trợ lý AI cho học sinh THCS ôn thi môn Tin học.
Nhiệm vụ của bạn là:
- Giải đáp thắc mắc về lập trình, thuật toán, cấu trúc dữ liệu
- Hướng dẫn học sinh giải bài tập tin học
- Giải thích các khái niệm tin học một cách dễ hiểu
- Trả lời bằng tiếng Việt, ngắn gọn và rõ ràng

QUAN TRỌNG: Trả lời bằng văn bản thuần túy, KHÔNG sử dụng bất kỳ ký tự định dạng nào như #, **, *, ```.

Câu hỏi: {user_message}

Trả lời:"""
        
        response = model.generate_content(full_prompt)
        clean_text = remove_markdown_formatting(response.text)
        return clean_text
    
    except Exception as e:
        return f"Xin lỗi, có lỗi xảy ra: {str(e)}"


def chat_with_context(user_message, chat_history=[]):
    if not GEMINI_API_KEY:
        return "Xin lỗi, dịch vụ AI chưa được cấu hình."
    
    try:
        model = genai.GenerativeModel(
            'gemini-2.5-flash',
            generation_config={
                'temperature': 0.7,
                'top_p': 0.95,
                'top_k': 40,
                'max_output_tokens': 2048,
            }
            # ← XÓA system_instruction
        )
        
        # Thêm system instruction vào đầu history
        gemini_history = [
            {
                'role': 'user',
                'parts': ['Bạn là trợ lý AI cho học sinh THCS ôn thi môn Tin học. Trả lời bằng văn bản thuần túy, KHÔNG sử dụng ký tự định dạng Markdown.']
            },
            {
                'role': 'model',
                'parts': ['Được rồi, tôi hiểu. Tôi sẽ trả lời bằng văn bản thuần túy và giúp các em học Tin học.']
            }
        ]
        
        # Thêm chat history
        for msg in chat_history:
            if msg['role'] == 'user':
                gemini_history.append({
                    'role': 'user',
                    'parts': [msg.get('content', msg.get('parts', [''])[0])]
                })
            elif msg['role'] in ['assistant', 'model']:
                gemini_history.append({
                    'role': 'model',
                    'parts': [msg.get('content', msg.get('parts', [''])[0])]
                })
        
        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(user_message)
        clean_text = remove_markdown_formatting(response.text)
        return clean_text
    
    except Exception as e:
        return f"Xin lỗi, có lỗi xảy ra: {str(e)}"


def get_gemini_response(prompt, temperature=0.7, max_tokens=4096):
    """
    Lấy response từ Gemini với config tùy chỉnh
    Dùng cho convert đề thi và các task phức tạp
    """
    if not GEMINI_API_KEY:
        raise Exception("Thiếu GEMINI_API_KEY. Vui lòng cấu hình trong file .env")
    
    try:
        model = genai.GenerativeModel(
            'gemini-2.5-flash',
            generation_config={
                'temperature': temperature,
                'max_output_tokens': max_tokens,
                'top_p': 0.95,
                'top_k': 40,
            }
        )
        
        response = model.generate_content(prompt)
        
        return response.text
    
    except Exception as e:
        raise Exception(f"Lỗi khi gọi Gemini API: {str(e)}")


# ==================== TEST CODE ====================
if __name__ == "__main__":
    print("=" * 60)
    print("TEST 1: chat_with_gemini (không context)")
    print("=" * 60)
    response1 = chat_with_gemini("Giải thích thuật toán sắp xếp nổi bọt là gì?")
    print(response1)
    
    print("\n" + "=" * 60)
    print("TEST 2: chat_with_context (có context)")
    print("=" * 60)
    
    # Lịch sử chat (format Gemini chuẩn)
    history = [
        {'role': 'user', 'parts': ['Độ phức tạp của bubble sort là gì?']},
        {'role': 'model', 'parts': ['Độ phức tạp của Bubble Sort là O(n^2) trong trường hợp xấu nhất và trung bình, O(n) trong trường hợp tốt nhất khi mảng đã sắp xếp.']},
    ]
    
    response2 = chat_with_context("Còn quick sort thì sao?", history)
    print(response2)
    
    print("\n" + "=" * 60)
    print("TEST 3: chat_with_context (format cũ - tương thích)")
    print("=" * 60)
    
    # Lịch sử chat (format cũ - vẫn hoạt động)
    old_history = [
        {'role': 'user', 'content': 'Python là gì?'},
        {'role': 'assistant', 'content': 'Python là ngôn ngữ lập trình bậc cao, dễ học, được dùng rộng rãi.'},
    ]
    
    response3 = chat_with_context("Nó có ưu điểm gì?", old_history)
    print(response3)