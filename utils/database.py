import json
import os
from datetime import datetime

SUPPORTED_GRADES = ['6', '7', '8', '9']

class Database:
    def __init__(self):
        self.courses_file = 'data/courses.json'
        self.exercises_file = 'data/exercises.json'
        self.progress_file = 'data/progress.json'
        self.documents_file = 'data/documents.json'
        self.submissions_file = 'data/submissions.json'
        self.forum_posts_file = 'data/forum_posts.json'
        self.forum_comments_file = 'data/forum_comments.json'
        self.chat_messages_file = 'data/chat_messages.json'
        self._init_files()
    
    def _init_files(self):
        files = [
            self.courses_file, 
            self.exercises_file, 
            self.progress_file, 
            self.documents_file,
            self.submissions_file,
            self.forum_posts_file,
            self.forum_comments_file,
            self.chat_messages_file
        ]
        for file in files:
            if not os.path.exists(file):
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump([], f)
    
    def _load_json(self, filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    def _save_json(self, filename, data):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _get_exam_file(self, grade):
        grade_str = str(grade)
        return f'data/lop{grade_str}.json'

    def load_exam_bank(self, grade):
        filename = self._get_exam_file(grade)
        if not os.path.exists(filename):
            return {'exams': []}
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault('exams', [])
                    exams = data.get('exams', [])
                if isinstance(data, list):
                    exams = data
                    data = {'exams': exams}
                if not isinstance(data, dict):
                    return {'exams': []}

                normalized_exams = []
                for exam in data.get('exams', []):
                    if not isinstance(exam, dict):
                        continue
                    exam.setdefault('questions', [])
                    exam.setdefault('allow_multiple_answers', False)
                    for question in exam.get('questions', []):
                        if not isinstance(question, dict):
                            continue
                        question.setdefault('type', 'standard')
                        if question.get('type') == 'tl2' and isinstance(question.get('correct_answer'), str):
                            question['correct_answer'] = [question['correct_answer']]
                    normalized_exams.append(exam)
                data['exams'] = normalized_exams
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            return {'exams': []}

    def save_exam_bank(self, grade, data):
        filename = self._get_exam_file(grade)
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        if not isinstance(data, dict):
            data = {'exams': data or []}
        elif 'exams' not in data:
            data['exams'] = []
        self._save_json(filename, data)

    def add_exam(self, grade, exam_data):
        exams_data = self.load_exam_bank(grade)
        exams = exams_data.setdefault('exams', [])
        exams.append(exam_data)
        self.save_exam_bank(grade, exams_data)
        return exam_data.get('id')

    def delete_exam(self, grade, exam_id):
        exams_data = self.load_exam_bank(grade)
        exams = exams_data.get('exams', [])
        new_exams = [exam for exam in exams if exam.get('id') != exam_id]
        if len(new_exams) == len(exams):
            return False
        exams_data['exams'] = new_exams
        self.save_exam_bank(grade, exams_data)
        return True

    def delete_exam_results(self, exam_id, grade=None):
        results = self._load_json('data/exam_results.json')
        if not results:
            return 0
        filtered = [
            result for result in results
            if not (
                result.get('exam_id') == exam_id and
                (grade is None or str(result.get('grade')) == str(grade))
            )
        ]
        removed = len(results) - len(filtered)
        if removed:
            self._save_json('data/exam_results.json', filtered)
        return removed

    def get_exams_by_teacher(self, teacher_id):
        exams_by_grade = {}
        for grade in SUPPORTED_GRADES:
            bank = self.load_exam_bank(grade)
            exams = [
                exam for exam in bank.get('exams', [])
                if exam.get('created_by') == teacher_id
            ]
            if exams:
                exams_by_grade[grade] = exams
        return exams_by_grade

    def get_all_courses(self):
        return self._load_json(self.courses_file)
    
    def get_course_by_id(self, course_id):
        courses = self.get_all_courses()
        return next((c for c in courses if c['id'] == course_id), None)
    
    def get_courses_by_teacher(self, teacher_id):
        courses = self.get_all_courses()
        return [c for c in courses if c['teacher_id'] == teacher_id]
    
    def create_course(self, course_data, teacher_id):
        courses = self.get_all_courses()
        course_id = f"course_{len(courses) + 1}"
        
        new_course = {
            'id': course_id,
            'teacher_id': teacher_id,
            'title': course_data['title'],
            'description': course_data.get('description', ''),
            'lessons': course_data.get('lessons', []),
            'created_at': datetime.now().isoformat()
        }
        
        courses.append(new_course)
        self._save_json(self.courses_file, courses)
        return course_id
    
    def update_course(self, course_id, course_data):
        courses = self.get_all_courses()
        for i, course in enumerate(courses):
            if course['id'] == course_id:
                courses[i].update(course_data)
                courses[i]['updated_at'] = datetime.now().isoformat()
                self._save_json(self.courses_file, courses)
                return True
        return False
    
    def get_all_exercises(self):
        return self._load_json(self.exercises_file)
    
    def save_exercise_submission(self, user_id, submission_data):
        submissions = self._load_json(self.submissions_file)
        
        submission = {
            'id': f"sub_{len(submissions) + 1}",
            'user_id': user_id,
            'course_id': submission_data.get('course_id'),
            'exercise_id': submission_data['exercise_id'],
            'answers': submission_data['answers'],
            'submitted_at': submission_data.get('submitted_at', datetime.now().isoformat())
        }
        
        submissions.append(submission)
        self._save_json(self.submissions_file, submissions)
        return submission['id']
    
    def get_student_progress(self, user_id):
        progress_list = self._load_json(self.progress_file)
        return [p for p in progress_list if p['user_id'] == user_id]
    
    def get_course_progress(self, user_id, course_id):
        progress_list = self._load_json(self.progress_file)
        return next((p for p in progress_list if p['user_id'] == user_id and p['course_id'] == course_id), None)
    
    def update_progress(self, user_id, course_id, lesson_id, completed, **kwargs):
        progress_list = self._load_json(self.progress_file)
        
        timestamp = kwargs.get('timestamp', datetime.now().isoformat())
        
        progress = next((p for p in progress_list if p['user_id'] == user_id and p['course_id'] == course_id), None)
        
        if progress:
            if completed and lesson_id not in progress['completed_lessons']:
                progress['completed_lessons'].append(lesson_id)
            progress['last_updated'] = timestamp
        else:
            progress = {
                'user_id': user_id,
                'course_id': course_id,
                'completed_lessons': [lesson_id] if completed else [],
                'last_updated': timestamp
            }
            progress_list.append(progress)
        
        self._save_json(self.progress_file, progress_list)
        return True
    
    def get_all_documents(self):
        return self._load_json(self.documents_file)
    
    def add_document(self, doc_data):
        documents = self.get_all_documents()
        doc_id = f"doc_{len(documents) + 1}"
        
        url = doc_data.get('url') or doc_data.get('link', '')
        
        new_doc = {
            'id': doc_id,
            'title': doc_data['title'],
            'url': url,
            'description': doc_data.get('description', ''),
            'grade': doc_data.get('grade', '12'),
            'doc_type': doc_data.get('doc_type', 'document'),
            'link_type': doc_data.get('link_type', 'other'),
            'category': doc_data.get('category', ''),
            'created_at': datetime.now().isoformat()
        }
        
        documents.append(new_doc)
        self._save_json(self.documents_file, documents)
        return doc_id
    def delete_document(self, doc_id):###################
        documents = self.get_all_documents()
        original_length = len(documents)
        documents = [d for d in documents if d['id'] != doc_id]
        
        if len(documents) < original_length:
            self._save_json(self.documents_file, documents)
            return True
        return False
    def get_all_submissions(self):
        return self._load_json(self.submissions_file)
    
    def get_submissions_by_course(self, course_id):
        submissions = self.get_all_submissions()
        return [s for s in submissions if s.get('course_id') == course_id]
    
    def get_all_forum_posts(self):
        posts = self._load_json(self.forum_posts_file)
        posts.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return posts
    
    def get_forum_post_by_id(self, post_id):
        posts = self._load_json(self.forum_posts_file)
        return next((p for p in posts if p['id'] == post_id), None)
    
    def get_forum_posts_by_user(self, user_id):
        posts = self.get_all_forum_posts()
        return [p for p in posts if p['author_id'] == user_id]
    
    def create_forum_post(self, post_data):
        posts = self._load_json(self.forum_posts_file)
        post_id = f"post_{len(posts) + 1:04d}"
        
        new_post = {
            'id': post_id,
            'title': post_data['title'],
            'content': post_data['content'],
            'author_id': post_data['author_id'],
            'author_name': post_data['author_name'],
            'author_role': post_data.get('author_role', 'student'),
            'created_at': datetime.now().isoformat(),
            'updated_at': None,
            'attachments': post_data.get('attachments', []),
            'tags': post_data.get('tags', []),
            'views': 0,
            'comments_count': 0
        }
        
        posts.append(new_post)
        self._save_json(self.forum_posts_file, posts)
        return post_id
    
    def update_forum_post(self, post_id, post_data):
        posts = self._load_json(self.forum_posts_file)
        
        for i, post in enumerate(posts):
            if post['id'] == post_id:
                if 'title' in post_data:
                    posts[i]['title'] = post_data['title']
                if 'content' in post_data:
                    posts[i]['content'] = post_data['content']
                if 'attachments' in post_data:
                    posts[i]['attachments'] = post_data['attachments']
                if 'tags' in post_data:
                    posts[i]['tags'] = post_data['tags']
                
                posts[i]['updated_at'] = datetime.now().isoformat()
                self._save_json(self.forum_posts_file, posts)
                return True
        
        return False
    
    def delete_forum_post(self, post_id):
        posts = self._load_json(self.forum_posts_file)
        posts = [p for p in posts if p['id'] != post_id]
        self._save_json(self.forum_posts_file, posts)
        
        comments = self._load_json(self.forum_comments_file)
        comments = [c for c in comments if c['post_id'] != post_id]
        self._save_json(self.forum_comments_file, comments)
        
        return True
    
    def increment_post_views(self, post_id):
        posts = self._load_json(self.forum_posts_file)
        
        for i, post in enumerate(posts):
            if post['id'] == post_id:
                posts[i]['views'] = posts[i].get('views', 0) + 1
                self._save_json(self.forum_posts_file, posts)
                return True
        
        return False
    
    def search_forum_posts(self, keyword):
        posts = self.get_all_forum_posts()
        keyword_lower = keyword.lower()
        
        return [
            p for p in posts 
            if keyword_lower in p['title'].lower() 
            or keyword_lower in p['content'].lower()
        ]
    
    def get_comments_by_post(self, post_id):
        comments = self._load_json(self.forum_comments_file)
        post_comments = [c for c in comments if c['post_id'] == post_id]
        post_comments.sort(key=lambda x: x.get('created_at', ''))
        return post_comments
    
    def add_comment(self, comment_data):
        comments = self._load_json(self.forum_comments_file)
        comment_id = f"comment_{len(comments) + 1:04d}"
        
        new_comment = {
            'id': comment_id,
            'post_id': comment_data['post_id'],
            'author_id': comment_data['author_id'],
            'author_name': comment_data['author_name'],
            'author_role': comment_data.get('author_role', 'student'),
            'content': comment_data['content'],
            'created_at': datetime.now().isoformat(),
            'attachments': comment_data.get('attachments', [])
        }
        
        comments.append(new_comment)
        self._save_json(self.forum_comments_file, comments)
        
        self._update_comments_count(comment_data['post_id'])
        
        return comment_id
    
    def delete_comment(self, comment_id):
        comments = self._load_json(self.forum_comments_file)
        
        comment = next((c for c in comments if c['id'] == comment_id), None)
        if not comment:
            return False
        
        post_id = comment['post_id']
        
        comments = [c for c in comments if c['id'] != comment_id]
        self._save_json(self.forum_comments_file, comments)
        
        self._update_comments_count(post_id)
        
        return True
    
    def _update_comments_count(self, post_id):
        posts = self._load_json(self.forum_posts_file)
        comments = self.get_comments_by_post(post_id)
        
        for i, post in enumerate(posts):
            if post['id'] == post_id:
                posts[i]['comments_count'] = len(comments)
                self._save_json(self.forum_posts_file, posts)
                break
    
    def get_all_chat_messages(self):
        messages = self._load_json(self.chat_messages_file)
        messages.sort(key=lambda x: x.get('created_at', ''))
        return messages

    def get_chat_message_by_id(self, message_id):
        messages = self._load_json(self.chat_messages_file)
        return next((m for m in messages if m['id'] == message_id), None)

    def add_chat_message(self, message_data):
        messages = self._load_json(self.chat_messages_file)
        message_id = f"msg_{len(messages) + 1:06d}"
        
        new_message = {
            'id': message_id,
            'content': message_data['content'],
            'author_id': message_data['author_id'],
            'author_name': message_data['author_name'],
            'author_role': message_data.get('author_role', 'student'),
            'created_at': datetime.now().isoformat(),
            'reply_to': message_data.get('reply_to')
        }
        
        messages.append(new_message)
        self._save_json(self.chat_messages_file, messages)
        return message_id

    def delete_chat_message(self, message_id):
        messages = self._load_json(self.chat_messages_file)
        messages = [m for m in messages if m['id'] != message_id]
        self._save_json(self.chat_messages_file, messages)
        return True

    def get_chat_messages_after(self, last_id):
        messages = self.get_all_chat_messages()
        
        if not last_id:
            return messages[-50:] if len(messages) > 50 else messages
        
        last_index = -1
        for i, msg in enumerate(messages):
            if msg['id'] == last_id:
                last_index = i
                break
        
        if last_index == -1:
            return []
        
        return messages[last_index + 1:]