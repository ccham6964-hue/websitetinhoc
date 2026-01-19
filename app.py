import json
import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.utils import secure_filename
from utils.ai_exam_converter import extract_text_from_docx, convert_exam_with_ai, validate_exam_data

import re
from docx import Document
from utils.gemini_api import get_gemini_response

from utils.auth import register_user, login_user, get_user_by_id
from utils.database import Database
from utils.exam_parser import ExamParseError, parse_docx_exam
from utils.gemini_api import chat_with_gemini

app = Flask(__name__)
load_dotenv()
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-me')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')

FORUM_UPLOAD_FOLDER = os.getenv('FORUM_UPLOAD_FOLDER', 'static/uploads/forum')
EXAM_UPLOAD_FOLDER = os.getenv('EXAM_UPLOAD_FOLDER', 'static/uploads/exams')
ALLOWED_EXAM_EXTENSIONS = {'docx'}


GRADE_LABELS = {
    '6': 'Lớp 6',
    '7': 'Lớp 7', 
    '8': 'Lớp 8',
    '9': 'Lớp 9'
}
AVAILABLE_GRADES = ['6', '7', '8', '9']
DEFAULT_GRADE = '6'
db = Database()
####

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập để tiếp tục', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập', 'warning')
            return redirect(url_for('login'))
        
        user = get_user_by_id(session['user_id'])
        if not user or user['role'] != 'teacher':
            flash('Chỉ giáo viên mới có quyền truy cập trang này', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

#################33
def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập', 'warning')
            return redirect(url_for('login'))
        
        user = get_user_by_id(session['user_id'])
        if not user or user['role'] != 'student':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    
    total_courses = len(db.get_all_courses())
    total_documents = len(db.get_all_documents())
    
    return render_template('index.html', 
                         total_courses=total_courses,
                         total_documents=total_documents)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        email = request.form.get('email', '').strip()
        
        if not username or not password or not email:
            flash('Vui lòng điền đầy đủ thông tin', 'danger')
            return render_template('register.html')
        
        result = register_user(username, password, email, role='student')
        
        if result['success']:
            flash('Đăng ký thành công! Vui lòng đăng nhập', 'success')
            return redirect(url_for('login'))
        else:
            flash(result['message'], 'danger')
            return render_template('register.html')
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Vui lòng nhập tên đăng nhập và mật khẩu', 'danger')
            return render_template('login.html')
        
        result = login_user(username, password)
        
        if result['success']:
            session['user_id'] = result['user_id']
            session['username'] = result['username']
            session['role'] = result['role']
            
            flash(f'Chào mừng {result["username"]}!', 'success')
            
            if result['role'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash(result['message'], 'danger')
            return render_template('login.html')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    username = session.get('username', 'Người dùng')
    session.clear()
    flash(f'Tạm biệt {username}!', 'info')
    return redirect(url_for('index'))


@app.route('/student/dashboard')
@login_required
@student_required
def student_dashboard():
    courses = db.get_all_courses()
    my_progress = db.get_student_progress(session['user_id'])
    
    enrolled_courses = []
    for progress in my_progress:
        course = db.get_course_by_id(progress['course_id'])
        if course:
            total_lessons = len(course.get('lessons', []))
            completed_lessons = len(progress.get('completed_lessons', []))
            percentage = (completed_lessons / total_lessons * 100) if total_lessons > 0 else 0
            
            enrolled_courses.append({
                'course': course,
                'progress': progress,
                'percentage': round(percentage, 1)
            })
    
    return render_template('student_dashboard.html', 
                         courses=courses,
                         enrolled_courses=enrolled_courses,
                         username=session.get('username'))


@app.route('/teacher/dashboard')
@login_required
@teacher_required
def teacher_dashboard():
    my_courses = db.get_courses_by_teacher(session['user_id'])
    
    course_stats = []
    for course in my_courses:
        all_progress = db._load_json(db.progress_file)
        students_enrolled = len([p for p in all_progress if p['course_id'] == course['id']])
        
        course_stats.append({
            'course': course,
            'students_enrolled': students_enrolled,
            'total_lessons': len(course.get('lessons', []))
        })
    
    return render_template('teacher_dashboard.html',
                         courses=course_stats,
                         username=session.get('username'))


@app.route('/courses')
@login_required
def courses():
    all_courses = db.get_all_courses()
    
    courses_with_teacher = []
    for course in all_courses:
        teacher = get_user_by_id(course['teacher_id'])
        course['teacher_name'] = teacher['username'] if teacher else 'Unknown'
        courses_with_teacher.append(course)
    
    return render_template('courses.html', courses=courses_with_teacher)


@app.route('/course/<course_id>')
@login_required
def course_detail(course_id):
    course = db.get_course_by_id(course_id)
    
    if not course:
        flash('Khóa học không tồn tại', 'danger')
        return redirect(url_for('courses'))
    
    teacher = get_user_by_id(course['teacher_id'])
    course['teacher_name'] = teacher['username'] if teacher else 'Unknown'
    
    progress = db.get_course_progress(session['user_id'], course_id)
    completed_lessons = progress['completed_lessons'] if progress else []
    
    is_teacher = session.get('role') == 'teacher' and course['teacher_id'] == session['user_id']
    
    return render_template('course_detail.html', 
                         course=course,
                         completed_lessons=completed_lessons,
                         is_teacher=is_teacher)


@app.route('/teacher/create_course', methods=['GET', 'POST'])
@teacher_required
def create_course():
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            if not data.get('title'):
                return jsonify({'success': False, 'message': 'Vui lòng nhập tên khóa học'})
            
            all_courses = db.get_all_courses()
            if any(c['title'].lower() == data['title'].lower() and c['teacher_id'] == session['user_id'] for c in all_courses):
                return jsonify({'success': False, 'message': 'Bạn đã có khóa học trùng tên này'})
            
            course_id = db.create_course(data, session['user_id'])
            
            return jsonify({'success': True, 'course_id': course_id, 'message': 'Tạo khóa học thành công'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    
    return render_template('create_course.html')


@app.route('/teacher/edit_course/<course_id>', methods=['GET', 'POST'])
@teacher_required
def edit_course(course_id):
    course = db.get_course_by_id(course_id)
    
    if not course:
        flash('Khóa học không tồn tại', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    if course['teacher_id'] != session['user_id']:
        flash('Bạn không có quyền chỉnh sửa khóa học này', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            success = db.update_course(course_id, data)
            
            if success:
                return jsonify({'success': True, 'message': 'Cập nhật khóa học thành công'})
            else:
                return jsonify({'success': False, 'message': 'Cập nhật thất bại'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    
    return render_template('create_course.html', course=course, edit_mode=True)


@app.route('/teacher/delete_course/<course_id>', methods=['POST'])
@teacher_required
def delete_course(course_id):
    course = db.get_course_by_id(course_id)
    
    if not course:
        return jsonify({'success': False, 'message': 'Khóa học không tồn tại'})
    
    if course['teacher_id'] != session['user_id']:
        return jsonify({'success': False, 'message': 'Bạn không có quyền xóa khóa học này'})
    
    courses = db.get_all_courses()
    courses = [c for c in courses if c['id'] != course_id]
    db._save_json(db.courses_file, courses)
    
    return jsonify({'success': True, 'message': 'Xóa khóa học thành công'})


@app.route('/exercises')
@login_required
def exercises():
    all_courses = db.get_all_courses()
    
    exercises_list = []
    for course in all_courses:
        for lesson in course.get('lessons', []):
            questions = lesson.get('questions', [])
            if questions:
                exercises_list.append({
                    'course_id': course['id'],
                    'course_title': course['title'],
                    'lesson_id': lesson['id'],
                    'lesson_title': lesson['title'],
                    'questions': questions
                })
    
    try:
        all_submissions = db._load_json(db.submissions_file) if hasattr(db, 'submissions_file') else []
    except:
        all_submissions = []
    
    my_submissions = [s for s in all_submissions if s.get('user_id') == session['user_id']]
    
    return render_template('exercises.html', 
                         exercises=exercises_list,
                         submissions=my_submissions)


@app.route('/submit_exercise', methods=['POST'])
@login_required
def submit_exercise():
    try:
        data = request.get_json()
        
        if not data.get('course_id') or not data.get('lesson_id') or not data.get('answers'):
            return jsonify({'success': False, 'message': 'Dữ liệu không đầy đủ'})
        
        submission_data = {
            'course_id': data['course_id'],
            'exercise_id': data['lesson_id'],
            'answers': data['answers'],
            'submitted_at': datetime.now().isoformat()
        }
        
        submission_id = db.save_exercise_submission(session['user_id'], submission_data)
        
        course = db.get_course_by_id(data['course_id'])
        if course:
            lesson = next((l for l in course.get('lessons', []) if l['id'] == data['lesson_id']), None)
            if lesson:
                questions = lesson.get('questions', [])
                correct = 0
                total = len(questions)
                
                for i, q in enumerate(questions):
                    user_answer_raw = data['answers'].get(str(i), '')
                    user_choice = normalize_answer_token(user_answer_raw)
                    correct_answers = normalize_correct_answers(q.get('correct_answer'))
                    
                    if user_choice and user_choice in correct_answers:
                        correct += 1
                
                score = round((correct / total * 100) if total > 0 else 0, 1)
                
                return jsonify({
                    'success': True,
                    'submission_id': submission_id,
                    'score': score,
                    'correct': correct,
                    'total': total,
                    'message': 'Nộp bài thành công'
                })
        
        return jsonify({'success': True, 'submission_id': submission_id, 'message': 'Nộp bài thành công'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})


@app.route('/documents')
@login_required
def documents():
    grade_filter = request.args.get('grade', 'all')
    type_filter = request.args.get('type', 'all')
    
    docs = db.get_all_documents()
    
    # ✅ Thêm giá trị mặc định cho documents cũ
    for doc in docs:
        if 'grade' not in doc or not doc.get('grade'):
            doc['grade'] = '6'  # Mặc định lớp 6
        if 'doc_type' not in doc or not doc.get('doc_type'):
            doc['doc_type'] = 'document'  # Mặc định là tài liệu
    
    if grade_filter != 'all':
        docs = [d for d in docs if str(d.get('grade')) == grade_filter]
    if type_filter != 'all':
        docs = [d for d in docs if d.get('doc_type') == type_filter]
    
    docs_by_grade = {
        grade: [d for d in docs if str(d.get('grade')) == grade]
        for grade in AVAILABLE_GRADES
    }
    
    return render_template('documents.html',
                         docs_by_grade=docs_by_grade,
                         current_grade=grade_filter,
                         current_type=type_filter,
                         grade_labels=GRADE_LABELS,
                         grade_choices=AVAILABLE_GRADES)
                         ################################################33



@app.route('/teacher/add_document', methods=['GET', 'POST'])
@teacher_required
def add_document():
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            if not data.get('title') or not data.get('url'):
                return jsonify({'success': False, 'message': 'Vui lòng nhập đầy đủ thông tin'})
            
            # Thêm trường grade và doc_type vào dữ liệu
            if not data.get('grade'):
                return jsonify({'success': False, 'message': 'Vui lòng chọn lớp học'})
            
            if not data.get('doc_type'):
                return jsonify({'success': False, 'message': 'Vui lòng chọn loại tài liệu'})
            
            if 'youtube.com' in data['url'] or 'youtu.be' in data['url']:
                data['link_type'] = 'youtube'
            elif 'drive.google.com' in data['url']:
                data['link_type'] = 'drive'
            else:
                data['link_type'] = data.get('link_type', 'other')
            
            doc_id = db.add_document(data)
            
            return jsonify({'success': True, 'doc_id': doc_id, 'message': 'Thêm tài liệu thành công'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    
    return render_template('add_document.html')

@app.route('/teacher/delete_document/<doc_id>', methods=['POST'])
@teacher_required
def delete_document(doc_id):
    try:
        success = db.delete_document(doc_id)
        if success:
            return jsonify({'success': True, 'message': 'Xóa tài liệu thành công'})
        else:
            return jsonify({'success': False, 'message': 'Không tìm thấy tài liệu'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})

######################################################################################################################
@app.route('/teacher/import_exam', methods=['GET', 'POST'])
@teacher_required
def import_exam():
    form_data = {
        'title': request.form.get('title', '').strip(),
        'description': request.form.get('description', '').strip(),
        'time_limit': request.form.get('time_limit', '').strip() or '15',
        'grade': request.form.get('grade', '').strip(),
        'allow_multiple': 'on' if request.form.get('allow_multiple') else 'off'
    } if request.method == 'POST' else {
        'title': '',
        'description': '',
        'time_limit': '15',
        'grade': DEFAULT_GRADE,
        'allow_multiple': 'off'
    }

    if request.method == 'POST':
        grade = form_data['grade']
        title = form_data['title']
        description = form_data['description']
        time_limit_raw = form_data['time_limit']
        exam_file = request.files.get('exam_file')
        allow_multiple = form_data['allow_multiple'] == 'on'

        errors = []
        if grade not in AVAILABLE_GRADES:
            errors.append('Vui lòng chọn khối lớp hợp lệ.')

        try:
            time_limit = int(time_limit_raw)
            if time_limit <= 0:
                raise ValueError
        except ValueError:
            errors.append('Thời gian làm bài phải là số nguyên dương (phút).')
            time_limit = 15

        if not title:
            errors.append('Vui lòng nhập tên đề thi.')

        if not exam_file or not exam_file.filename:
            errors.append('Vui lòng chọn file .docx cần import.')
        elif not allowed_exam_file(exam_file.filename):
            errors.append('Chỉ hỗ trợ file định dạng .docx.')

        if errors:
            for message in errors:
                flash(message, 'danger')
            return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)

        secure_name = secure_filename(exam_file.filename)
        ensure_directory(EXAM_UPLOAD_FOLDER)
        temp_filename = f"{uuid.uuid4().hex}_{secure_name}"
        temp_path = os.path.join(EXAM_UPLOAD_FOLDER, temp_filename)
        exam_file.save(temp_path)

        parsed_questions = []

        try:
            parsed_questions = parse_docx_exam(temp_path, allow_multiple_answers=False)
        except ExamParseError as exc:
            error_message = str(exc)
            if 'nhiều đáp án đúng' in error_message.lower():
                try:
                    parsed_questions = parse_docx_exam(temp_path, allow_multiple_answers=True)
                except ExamParseError as re_exc:
                    flash(f'Lỗi khi đọc file đề: {re_exc}', 'danger')
                    os.remove(temp_path)
                    return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)
                except Exception as re_exc:
                    flash(f'Lỗi không xác định khi xử lý file: {re_exc}', 'danger')
                    os.remove(temp_path)
                    return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)
            else:
                flash(f'Lỗi khi đọc file đề: {exc}', 'danger')
                os.remove(temp_path)
                return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)
        except Exception as exc:
            flash(f'Lỗi không xác định khi xử lý file: {exc}', 'danger')
            os.remove(temp_path)
            return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

        if not parsed_questions:
            flash('Không tìm thấy câu hỏi trắc nghiệm nào trong file.', 'danger')
            return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)

        questions_with_multiple = [
            item.get('number')
            for item in parsed_questions
            if len(normalize_correct_answers(item.get('correct_answer'))) > 1
        ]

        if questions_with_multiple and not allow_multiple:
            question_list = ', '.join(str(num) for num in questions_with_multiple[:5])
            more_suffix = '...' if len(questions_with_multiple) > 5 else ''
            flash(
                f'Đề thi có các câu {question_list}{more_suffix} được đánh dấu nhiều đáp án đúng. '
                'Vui lòng bật tùy chọn "Cho phép nhiều đáp án đúng" trước khi import.',
                'warning'
            )
            form_data['allow_multiple'] = 'on'
            return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)

        questions = []
        has_tl2_question = False
        for idx, item in enumerate(parsed_questions, start=1):
            options = item.get('options', {})
            correct_answer = item.get('correct_answer')
            question_type = item.get('type', 'tl1')

            if not options or len(options) < 2:
                flash(f'Câu {item.get("number", idx)} không có đủ lựa chọn.', 'danger')
                return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)

            if question_type == 'tl2':
                has_tl2_question = True
                if len(options) != 4:
                    flash(f'Câu {item.get("number", idx)} (TL2) cần đúng 4 ý để đánh giá Đúng/Sai.', 'danger')
                    return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)

            option_keys = {key.upper(): key for key in options.keys()}
            correct_tokens = normalize_correct_answers(correct_answer)
            if not correct_tokens:
                flash(f'Không xác định được đáp án đúng cho câu {item.get("number", idx)}.', 'danger')
                return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)

            invalid_tokens = [token for token in correct_tokens if token not in option_keys]
            if invalid_tokens:
                flash(
                    f'Đáp án {", ".join(invalid_tokens)} của câu {item.get("number", idx)} không trùng với lựa chọn A/B/C/D.',
                    'danger'
                )
                return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)

            def convert_token(token):
                # Map back to original key casing (A vs a) if needed
                return option_keys.get(token, token)

            if question_type == 'tl2':
                normalized_correct = [convert_token(token) for token in sorted(correct_tokens)]
            else:
                if len(correct_tokens) > 1:
                    normalized_correct = [convert_token(token) for token in sorted(correct_tokens)]
                    if len(normalized_correct) == 1:
                        normalized_correct = normalized_correct[0]
                else:
                    normalized_correct = convert_token(next(iter(correct_tokens)))

            questions.append({
                'id': item.get('number', idx),
                'number': item.get('number', idx),
                'question': item.get('question', '').strip(),
                'options': options,
                'correct_answer': normalized_correct,
                'explanation': item.get('explanation', '').strip(),
                'type': question_type
            })

        exam_id = f"exam_{grade}_{uuid.uuid4().hex[:6]}"
        exam_record = {
            'id': exam_id,
            'title': title,
            'description': description,
            'time_limit': time_limit,
            'questions': questions,
            'allow_multiple_answers': bool(questions_with_multiple or has_tl2_question),
            'created_by': session.get('user_id'),
            'created_by_name': session.get('username'),
            'created_at': datetime.now().isoformat()
        }

        try:
            db.add_exam(grade, exam_record)
        except Exception as exc:
            flash(f'Không thể lưu đề thi: {exc}', 'danger')
            return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)

        flash(f'Đã tạo đề thi "{title}" với {len(questions)} câu hỏi cho khối {grade}.', 'success')
        return redirect(url_for('tracnghiem'))

    return render_template('import_exam.html', form_data=form_data, grade_choices=AVAILABLE_GRADES, grade_labels=GRADE_LABELS)


@app.route('/chatbot')
@login_required
def chatbot():
    return render_template('chatbot.html', username=session.get('username'))


@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        
        if not message:
            return jsonify({'success': False, 'response': 'Vui lòng nhập tin nhắn'})
        
        response = chat_with_gemini(message)
        
        return jsonify({'success': True, 'response': response})
    
    except Exception as e:
        return jsonify({'success': False, 'response': f'Xin lỗi, có lỗi xảy ra: {str(e)}'})


@app.route('/update_progress', methods=['POST'])
@login_required
def update_progress():
    try:
        data = request.get_json()
        
        if not data.get('course_id') or not data.get('lesson_id'):
            return jsonify({'success': False, 'message': 'Dữ liệu không đầy đủ'})
        
        db.update_progress(
            session['user_id'],
            data['course_id'],
            data['lesson_id'],
            data.get('completed', True),
            timestamp=datetime.now().isoformat()
        )
        
        return jsonify({'success': True, 'message': 'Cập nhật tiến độ thành công'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})


@app.route('/teacher/students_progress')
@teacher_required
def students_progress():
    teacher_courses = db.get_courses_by_teacher(session['user_id'])
    teacher_course_ids = [c['id'] for c in teacher_courses]
    
    all_progress = db._load_json(db.progress_file)
    filtered_progress = [p for p in all_progress if p['course_id'] in teacher_course_ids]
    
    progress_with_details = []
    for prog in filtered_progress:
        student = get_user_by_id(prog['user_id'])
        course = db.get_course_by_id(prog['course_id'])
        
        if student and course:
            total_lessons = len(course.get('lessons', []))
            completed = len(prog.get('completed_lessons', []))
            percentage = round((completed / total_lessons * 100) if total_lessons > 0 else 0, 1)
            
            progress_with_details.append({
                'student_name': student['username'],
                'student_email': student.get('email', ''),
                'course_title': course['title'],
                'completed': completed,
                'total': total_lessons,
                'percentage': percentage,
                'last_updated': prog.get('last_updated', 'Chưa cập nhật')
            })

    return render_template('student_progress.html', progress=progress_with_details)

@app.route('/teacher/exams')
@login_required
@teacher_required
def teacher_exams():
    teacher_id = session.get('user_id')
    exams_by_grade = {}

    for grade in AVAILABLE_GRADES:
        bank = db.load_exam_bank(grade)
        grade_exams = []

        for exam in bank.get('exams', []):
            exam_copy = {
                'id': exam.get('id'),
                'title': exam.get('title', 'Không có tiêu đề'),
                'description': exam.get('description', ''),
                'time_limit': exam.get('time_limit', 15),
                'question_count': len(exam.get('questions', [])),
                'created_at': exam.get('created_at'),
                'allow_multiple_answers': exam.get('allow_multiple_answers', False),
                'created_by': exam.get('created_by'),
                'created_by_name': exam.get('created_by_name', 'Không rõ'),
                'grade': grade,
            }
            exam_copy['is_owner'] = exam_copy['created_by'] == teacher_id or exam_copy['created_by'] is None
            grade_exams.append(exam_copy)

        exams_by_grade[grade] = grade_exams

    return render_template('teacher_exams.html',
                           exams_by_grade=exams_by_grade,
                           grade_labels=GRADE_LABELS,
                           grade_order=AVAILABLE_GRADES,
                           username=session.get('username'))

@app.route('/teacher/delete_exam', methods=['POST'])
@login_required
@teacher_required
def delete_exam():
    try:
        data = request.get_json() or {}
        grade = str(data.get('grade', '')).strip()
        exam_id = data.get('exam_id')

        if grade not in AVAILABLE_GRADES or not exam_id:
            return jsonify({'success': False, 'message': 'Thiếu thông tin đề thi'}), 400

        bank = db.load_exam_bank(grade)
        exam = next((e for e in bank.get('exams', []) if e.get('id') == exam_id), None)

        if not exam:
            return jsonify({'success': False, 'message': 'Không tìm thấy đề thi'}), 404

        owner_id = exam.get('created_by')
        if owner_id and owner_id != session.get('user_id'):
            return jsonify({'success': False, 'message': 'Bạn chỉ có thể xoá đề thi do mình tạo'}), 403

        if not db.delete_exam(grade, exam_id):
            return jsonify({'success': False, 'message': 'Không thể xoá đề thi'}), 500

        removed_results = db.delete_exam_results(exam_id, grade)

        return jsonify({
            'success': True,
            'message': 'Đã xoá đề thi và xoá kết quả liên quan.' if removed_results else 'Đã xoá đề thi.',
            'removed_results': removed_results
        })
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Lỗi: {exc}'}), 500


@app.route('/teacher/view_submissions')
@teacher_required
def view_submissions():
    teacher_courses = db.get_courses_by_teacher(session['user_id'])
    teacher_course_ids = [c['id'] for c in teacher_courses]
    
    try:
        all_submissions = db._load_json(db.submissions_file) if hasattr(db, 'submissions_file') else []
    except:
        all_submissions = []
    
    filtered_submissions = [s for s in all_submissions if s.get('course_id') in teacher_course_ids]
    
    submissions_with_details = []
    for sub in filtered_submissions:
        student = get_user_by_id(sub['user_id'])
        course = db.get_course_by_id(sub.get('course_id'))
        
        if student and course:
            submissions_with_details.append({
                'student_name': student['username'],
                'course_title': course['title'],
                'exercise_id': sub.get('exercise_id'),
                'answers': sub.get('answers', {}),
                'submitted_at': sub.get('submitted_at', 'Không rõ')
            })
    
    return render_template('view_submissions.html', submissions=submissions_with_details)


@app.route('/api/course/<course_id>')
@login_required
def api_get_course(course_id):
    course = db.get_course_by_id(course_id)
    if course:
        return jsonify({'success': True, 'course': course})
    return jsonify({'success': False, 'error': 'Course not found'}), 404


@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500



########################
###############33
@app.route('/tracnghiem/lam-bai/<grade>/<exam_id>')
@login_required
def lam_bai_tracnghiem(grade, exam_id):
    """
    Hiển thị đề trắc nghiệm để học sinh làm bài
     Fix: Logic thời gian chặt chẽ, xử lý session an toàn
    """
    if grade not in AVAILABLE_GRADES:
        flash('Lớp không hợp lệ', 'danger')
        return redirect(url_for('tracnghiem'))
    
    json_file = f'data/lop{grade}.json'
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            exams_data = json.load(f)
            exams = exams_data.get('exams', [])
            
            exam = next((e for e in exams if e['id'] == exam_id), None)
            
            if not exam:
                flash('Đề thi không tồn tại', 'danger')
                return redirect(url_for('tracnghiem'))
            
            time_limit = exam.get('time_limit', 15)
            
            if not isinstance(time_limit, (int, float)) or time_limit <= 0:
                time_limit = 15
                print(f"Warning: Invalid time_limit in exam {exam_id}, using default 15 minutes")
            
            session_key = f'exam_start_{grade}_{exam_id}'
            reset_param = request.args.get('reset', 'no')
            
            if not session.permanent:
                session.permanent = True
                session.modified = True
            

            should_create_new_session = False
            remaining_time = time_limit * 60  # Mặc định
            
            if reset_param == 'yes':
                should_create_new_session = True
                print(f"Reset session for exam {exam_id}")
            
            elif session_key not in session:
                should_create_new_session = True
                print(f"New session for exam {exam_id}")
            else:
                try:
                    start_time_str = session.get(session_key)
                    if not start_time_str or not isinstance(start_time_str, str):
                        raise ValueError("Invalid start_time format")
                    
                    start_time = datetime.fromisoformat(start_time_str)
                    current_time = datetime.now()
                    
                    elapsed_seconds = (current_time - start_time).total_seconds()
                    
                    if elapsed_seconds < 0:
                        print(f"ERROR: Negative elapsed time for exam {exam_id}")
                        should_create_new_session = True
                    elif elapsed_seconds > (time_limit * 60 * 2):
                        print(f"WARNING: Session too old for exam {exam_id}")
                        should_create_new_session = True
                    else:
                        remaining_time = (time_limit * 60) - elapsed_seconds
                        

                        if remaining_time <= 0:
                            flash('⏰ Đã hết thời gian làm bài! Vui lòng làm lại từ đầu.', 'warning')
                            # Xóa session cũ
                            session.pop(session_key, None)
                            session.modified = True
                            return redirect(url_for('tracnghiem'))
                        
                        print(f"Exam {exam_id}: {int(remaining_time)}s remaining")
                
                except (ValueError, KeyError, TypeError, AttributeError) as e:
                    print(f"Session error for exam {exam_id}: {e}")
                    should_create_new_session = True
            
            if should_create_new_session:
                current_time = datetime.now()
                session[session_key] = current_time.isoformat()
                session.permanent = True
                session.modified = True
                remaining_time = time_limit * 60
                print(f"Created new session for exam {exam_id}, expires in {time_limit} minutes")
            

            remaining_time = max(1, min(remaining_time, time_limit * 60))
            remaining_time = int(remaining_time)  # Convert to integer
            
            # . LOG (cho debug)
            print(f"""
            ===== EXAM SESSION INFO =====
            Exam: {exam_id} | Grade: {grade}
            Time Limit: {time_limit} minutes
            Remaining: {remaining_time} seconds ({remaining_time//60}m {remaining_time%60}s)
            Session Key: {session_key}
            Session Permanent: {session.permanent}
            ============================
            """)
            

            for question in exam.get('questions', []):
                if isinstance(question, dict):
                    question.setdefault('type', 'tl1')
                    if question.get('type') == 'tl2' and isinstance(question.get('correct_answer'), str):
                        question['correct_answer'] = [question['correct_answer']]
            has_tl2 = any(q.get('type') == 'tl2' for q in exam.get('questions', []))

            return render_template('baitap.html',
                                 exam=exam,
                                 grade=grade,
                                 time_limit=time_limit,
                                 remaining_time=remaining_time,
                                 username=session.get('username'),
                                 has_tl2=has_tl2)
    
    except FileNotFoundError:
        flash(' Không tìm thấy dữ liệu đề thi', 'danger')
        return redirect(url_for('tracnghiem'))
    
    except json.JSONDecodeError as e:
        flash(' Dữ liệu đề thi bị lỗi định dạng', 'danger')
        print(f"JSON decode error: {e}")
        return redirect(url_for('tracnghiem'))
    
    except Exception as e:
        flash(f' Lỗi không xác định: {str(e)}', 'danger')
        print(f"Unexpected error in lam_bai_tracnghiem: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('tracnghiem'))



@app.route('/api/tracnghiem/check-time/<grade>/<exam_id>')
@login_required
def api_check_exam_time(grade, exam_id):
    """
    API kiểm tra thời gian còn lại - GỌI TỪ JAVASCRIPT
    Trả về: remaining_time (seconds) hoặc is_expired=True
    """
    session_key = f'exam_start_{grade}_{exam_id}'
    
    if session_key not in session:
        return jsonify({
            'success': False,
            'message': 'Session không tồn tại',
            'is_expired': True,
            'remaining_time': 0
        })
    
    try:
        json_file = f'data/lop{grade}.json'
        with open(json_file, 'r', encoding='utf-8') as f:
            exams_data = json.load(f)
            exams = exams_data.get('exams', [])
            exam = next((e for e in exams if e['id'] == exam_id), None)
            
            if not exam:
                return jsonify({
                    'success': False,
                    'message': 'Đề thi không tồn tại',
                    'is_expired': True,
                    'remaining_time': 0
                })
            
            time_limit = exam.get('time_limit', 15)
        

        start_time = datetime.fromisoformat(session[session_key])
        elapsed_seconds = (datetime.now() - start_time).total_seconds()
        remaining_seconds = (time_limit * 60) - elapsed_seconds
        
        # Validate
        if remaining_seconds <= 0:
            # Hết giờ - xóa session
            session.pop(session_key, None)
            session.modified = True
            
            return jsonify({
                'success': True,
                'remaining_time': 0,
                'is_expired': True,
                'message': 'Hết thời gian'
            })
        
        return jsonify({
            'success': True,
            'remaining_time': int(remaining_seconds),
            'is_expired': False,
            'time_limit_minutes': time_limit
        })
    
    except (ValueError, KeyError, TypeError) as e:
        print(f"Error in api_check_exam_time: {e}")
        return jsonify({
            'success': False,
            'message': f'Lỗi session: {str(e)}',
            'is_expired': True,
            'remaining_time': 0
        })
    
    except Exception as e:
        print(f"Unexpected error in api_check_exam_time: {e}")
        return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}',
            'is_expired': True,
            'remaining_time': 0
        })



@app.route('/tracnghiem')
@login_required
def tracnghiem():
    """
    Trang chọn đề thi trắc nghiệm
    """
    print("========= DEBUG TRACNGHIEM =========")
    print(f"User ID: {session.get('user_id')}")
    print(f"Role: {session.get('role')}")
    print(f"Username: {session.get('username')}")
    print("====================================")
    
    try:
        exams_by_grade = {grade: [] for grade in AVAILABLE_GRADES}

        # Đọc đề thi từ tất cả các khối
        for grade in AVAILABLE_GRADES:
            json_file = f'data/lop{grade}.json'
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    exams_data = json.load(f)
                    exams = exams_data.get('exams', [])

                    for exam in exams:
                        exam['grade'] = grade
                    exams_by_grade[grade].extend(exams)
                    print(f"✓ Loaded {len(exams)} exams from grade {grade}")

            except FileNotFoundError:
                print(f"✗ File {json_file} không tồn tại")
                continue
            except json.JSONDecodeError:
                print(f"✗ File {json_file} bị lỗi định dạng")
                continue

        total_exams = sum(len(exams) for exams in exams_by_grade.values())
        print(f"Total exams: {total_exams}")
        for grade in AVAILABLE_GRADES:
            print(f"Grade {grade}: {len(exams_by_grade[grade])}")

        return render_template('tracnghiem.html',
                             exams_by_grade=exams_by_grade,
                             grade_labels=GRADE_LABELS,
                             grade_order=AVAILABLE_GRADES,
                             username=session.get('username'))
    
    except Exception as e:
        print(f"ERROR in tracnghiem route: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Lỗi khi tải danh sách đề thi: {str(e)}', 'danger')
        return redirect(url_for('student_dashboard'))

############
@app.route('/tracnghiem/ket-qua/<grade>/<exam_id>')
@login_required
def ket_qua_tracnghiem(grade, exam_id):
    """
    Hiển thị kết quả bài làm với AI Analysis
    """
    try:
        user_id = session.get('user_id')
        results_file = 'data/exam_results.json'
        
        try:
            with open(results_file, 'r', encoding='utf-8') as f:
                all_results = json.load(f)
        except FileNotFoundError:
            flash('Không tìm thấy kết quả bài làm', 'warning')
            return redirect(url_for('tracnghiem'))
        
        # Lấy kết quả phù hợp
        matching_results = [
            r for r in all_results 
            if r.get('user_id') == user_id 
            and r.get('grade') == grade 
            and r.get('exam_id') == exam_id
        ]
        
        if not matching_results:
            flash('Không tìm thấy kết quả bài làm', 'warning')
            return redirect(url_for('tracnghiem'))
        
        result = matching_results[-1]
        
        # ===== LẤY ĐỀ THI ĐỂ HIỂN THỊ CHI TIẾT CÂU SAI =====
        json_file = f'data/lop{grade}.json'
        wrong_answers = []
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                exams_data = json.load(f)
                exams = exams_data.get('exams', [])
                exam = next((e for e in exams if e['id'] == exam_id), None)
                
                if exam:
                    questions = exam.get('questions', [])
                    details = result.get('details', [])
                    
                    for detail in details:
                        if not detail.get('is_correct', True):  # Câu sai
                            q_id = str(detail.get('question_id'))
                            question = next((q for q in questions if str(q.get('id')) == q_id), None)
                            
                            if question:
                                wrong_answers.append({
                                    'question_number': question.get('number', q_id),
                                    'question_text': question.get('question', ''),
                                    'user_answer': format_answer(detail.get('user_answer')),
                                    'correct_answer': format_answer(detail.get('correct_answer')),
                                    'explanation': question.get('explanation', '')
                                })
        except Exception as e:
            print(f"⚠️ Không thể tải chi tiết câu sai: {e}")
        
        # ===== TẠO AI ANALYSIS =====
        ai_analysis = None
        if result.get('score') is not None:
            try:
                ai_analysis = generate_ai_analysis(result)
                print(f"✅ Generated AI analysis for exam {exam_id}")
            except Exception as ai_error:
                print(f"⚠️ AI analysis failed: {ai_error}")
        
        return render_template('ketqua.html', 
                             result=result,
                             ai_analysis=ai_analysis,
                             wrong_answers=wrong_answers,  # ← THÊM DÒNG NÀY
                             username=session.get('username'))
    
    except Exception as e:
        print(f"ERROR in ket_qua_tracnghiem: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Lỗi khi hiển thị kết quả: {str(e)}', 'danger')
        return redirect(url_for('tracnghiem'))


def format_answer(answer):
    """Format đáp án để hiển thị"""
    if isinstance(answer, list):
        return ', '.join(str(a) for a in answer)
    return str(answer) if answer else '--'


def generate_ai_analysis(result):
    """
    Tạo phân tích AI dựa trên kết quả bài làm
    
    Args:
        result: Dict chứa thông tin kết quả bài thi
        
    Returns:
        Dict chứa AI analysis hoặc None nếu lỗi
    """
    try:
        score = result.get('score', 0)
        correct_count = result.get('correct_count', 0)
        total_questions = result.get('total_questions', 1)
        exam_title = result.get('exam_title', 'bài thi')
        
        # Tính phần trăm đúng
        percentage = (correct_count / total_questions * 100) if total_questions > 0 else 0
        
        # Tạo prompt cho AI
        prompt = f"""Bạn là trợ lý AI giáo dục chuyên nghiệp. Hãy phân tích kết quả bài thi của học sinh.

**THÔNG TIN BÀI THI:**
- Đề thi: {exam_title}
- Điểm số: {score}/10
- Số câu đúng: {correct_count}/{total_questions} ({percentage:.1f}%)

**YÊU CẦU:**
Hãy tạo một bản phân tích chi tiết, khuyến khích và xây dựng với các phần sau:

1. **overall_assessment**: Đánh giá tổng quan ngắn gọn (2-3 câu) về kết quả, giọng điệu tích cực và động viên

2. **strengths**: Liệt kê 2-3 điểm mạnh của học sinh (dựa trên tỷ lệ đúng)
   - Nếu điểm >=8: nhấn mạnh sự xuất sắc, kiến thức vững
   - Nếu 5-7.9: nhấn mạnh những phần đã làm tốt
   - Nếu <5: tìm điểm tích cực (nỗ lực, thái độ học tập...)

3. **weaknesses**: Chỉ ra 2-3 điểm cần cải thiện (giọng nhẹ nhàng, xây dựng)
   - KHÔNG dùng từ tiêu cực như "yếu kém", "tệ"
   - Dùng "cần chú ý thêm", "có thể cải thiện"

4. **study_plan**: Đưa ra 3-4 bước cụ thể để cải thiện
   - Mỗi bước phải rõ ràng, khả thi
   - Ưu tiên hành động thực tế

5. **encouragement**: Một câu động viên chân thành và ấm áp (1-2 câu)

**ĐỊNH DẠNG TRẢ LỜI (JSON):**
{{
    "overall_assessment": "...",
    "strengths": "• Điểm mạnh 1\\n• Điểm mạnh 2\\n• Điểm mạnh 3",
    "weaknesses": "• Điểm cần cải thiện 1\\n• Điểm cần cải thiện 2",
    "study_plan": "• Bước 1\\n• Bước 2\\n• Bước 3\\n• Bước 4",
    "encouragement": "..."
}}

**LƯU Ý:**
- Dùng \\n để xuống dòng giữa các điểm
- Giọng văn thân thiện, động viên
- Tập trung vào giải pháp, không chỉ trích
- Phù hợp với học sinh THCS (12-15 tuổi)

Chỉ trả về JSON, không giải thích thêm."""

        # Gọi Gemini API
        response = get_gemini_response(prompt)
        
        # Parse JSON
        import re
        json_match = re.search(r'\{[^{}]*"overall_assessment"[^{}]*\}', response, re.DOTALL)
        
        if json_match:
            analysis = json.loads(json_match.group(0))
            
            # Validate các trường bắt buộc
            required_fields = ['overall_assessment', 'strengths', 'weaknesses', 'study_plan', 'encouragement']
            for field in required_fields:
                if field not in analysis or not analysis[field]:
                    raise ValueError(f"Missing field: {field}")
            
            return analysis
        else:
            # Fallback: tạo analysis cơ bản
            return create_fallback_analysis(score, percentage)
    
    except Exception as e:
        print(f"Error generating AI analysis: {e}")
        # Trả về fallback analysis
        return create_fallback_analysis(result.get('score', 0), 
                                       (result.get('correct_count', 0) / result.get('total_questions', 1) * 100))


def create_fallback_analysis(score, percentage):
    """
    Tạo phân tích dự phòng khi AI không khả dụng
    """
    if score >= 8:
        overall = "Xuất sắc! Bạn đã thể hiện sự nắm vững kiến thức tốt. Tiếp tục duy trì phong độ này!"
        strengths = "• Nắm vững kiến thức cơ bản\n• Làm bài tập chính xác\n• Tư duy logic tốt"
        weaknesses = "• Có thể nâng cao tốc độ làm bài\n• Rèn luyện thêm các dạng khó"
        encouragement = "Tuyệt vời! Hãy tiếp tục phát huy! 🌟"
    
    elif score >= 5:
        overall = f"Khá tốt! Bạn đã hoàn thành {percentage:.0f}% bài thi. Còn một chút nữa là đạt điểm cao!"
        strengths = "• Có nền tảng kiến thức ổn định\n• Nỗ lực trong quá trình học\n• Tiềm năng phát triển tốt"
        weaknesses = "• Cần ôn tập thêm một số phần\n• Luyện tập nhiều dạng bài hơn\n• Chú ý đọc kỹ đề"
        encouragement = "Bạn đang trên đúng hướng! Cố gắng thêm một chút nữa nhé! 💪"
    
    else:
        overall = f"Bạn đã cố gắng hoàn thành bài thi. Đây là cơ hội tốt để học hỏi và cải thiện!"
        strengths = "• Có thái độ học tập tích cực\n• Dám thử sức với đề thi\n• Sẵn sàng học hỏi và tiến bộ"
        weaknesses = "• Cần củng cố kiến thức cơ bản\n• Dành thời gian ôn tập đều đặn\n• Làm nhiều bài tập hơn"
        encouragement = "Đừng nản chí! Mỗi lần làm bài là một cơ hội để tiến bộ! 🌱"
    
    study_plan = """• Ôn lại lý thuyết cơ bản mỗi ngày 30 phút
• Làm thêm 5-10 bài tập tương tự
• Ghi chép những điều chưa hiểu và hỏi giáo viên
• Tự kiểm tra kiến thức định kỳ"""
    
    return {
        'overall_assessment': overall,
        'strengths': strengths,
        'weaknesses': weaknesses,
        'study_plan': study_plan,
        'encouragement': encouragement
    }
##########

@app.route('/tracnghiem/lich-su')
@login_required
def lich_su_tracnghiem():
    """
    Hiển thị lịch sử làm bài trắc nghiệm của học sinh
    """
    try:
        user_id = session.get('user_id')
        results_file = 'data/exam_results.json'
        
        try:
            with open(results_file, 'r', encoding='utf-8') as f:
                all_results = json.load(f)
        except FileNotFoundError:
            all_results = []
        except json.JSONDecodeError:
            print("ERROR: exam_results.json bị lỗi định dạng")
            all_results = []
        

        user_results = [r for r in all_results if r.get('user_id') == user_id]
        user_results.sort(key=lambda x: x.get('submitted_at', ''), reverse=True)
        
        print(f"User {user_id} có {len(user_results)} bài đã làm")
        
        return render_template('lichsu_tracnghiem.html', 
                             results=user_results,
                             username=session.get('username'))
    
    except Exception as e:
        print(f"ERROR in lich_su_tracnghiem: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Lỗi khi tải lịch sử: {str(e)}', 'danger')
        return redirect(url_for('tracnghiem'))


@app.route('/tracnghiem/reset/<grade>/<exam_id>')
@login_required

def reset_exam_session(grade, exam_id):
    """
    Reset session để làm lại bài thi
    """
    session_key = f'exam_start_{grade}_{exam_id}'
    
    if session_key in session:
        session.pop(session_key)
        session.modified = True
        flash('Đã reset bài thi. Bạn có thể làm lại từ đầu!', 'success')
    
    return redirect(url_for('lam_bai_tracnghiem', grade=grade, exam_id=exam_id, reset='yes'))



        ####################
@app.route('/tracnghiem/nop-bai', methods=['POST'])
@login_required
def nop_bai_tracnghiem():
    """
    API xử lý nộp bài trắc nghiệm - GỌI TỪ JAVASCRIPT
    """
    try:
        data = request.get_json()
        
        # Validate dữ liệu đầu vào
        if not data or not data.get('grade') or not data.get('exam_id'):
            return jsonify({
                'success': False,
                'message': 'Thiếu thông tin đề thi'
            }), 400
        
        grade = data.get('grade')
        exam_id = data.get('exam_id')
        answers = data.get('answers', {})
        user_id = session.get('user_id')
        
        # Đọc đề thi để chấm điểm
        json_file = f'data/lop{grade}.json'
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                exams_data = json.load(f)
                exams = exams_data.get('exams', [])
                exam = next((e for e in exams if e['id'] == exam_id), None)
                
                if not exam:
                    return jsonify({
                        'success': False,
                        'message': 'Đề thi không tồn tại'
                    }), 404
        
        except FileNotFoundError:
            return jsonify({
                'success': False,
                'message': 'File đề thi không tồn tại'
            }), 404
        
        # Chấm điểm
        questions = exam.get('questions', [])
        total_questions = len(questions)
        correct_count = 0
        total_score_float = 0.0
        details = []
        
        for q in questions:
            q_id = str(q.get('id'))
            q_type = q.get('type', 'tl1')
            correct_answer = q.get('correct_answer')
            user_answer = answers.get(q_id)
            
            is_correct = False
            score_for_question = 0.0
            
            if q_type == 'tl2':
                # Câu TL2: tính điểm theo số sai
                if isinstance(correct_answer, list) and isinstance(user_answer, list):
                    correct_set = set(correct_answer)
                    user_set = set(user_answer)
                    mistakes = len(correct_set.symmetric_difference(user_set))
                    score_for_question = calculate_tl2_score(mistakes)
                    
                    if mistakes == 0:
                        is_correct = True
                        correct_count += 1
                
                total_score_float += score_for_question
            
            else:
                # Câu TL1: đúng/sai
                if isinstance(correct_answer, list):
                    is_correct = set(user_answer) == set(correct_answer) if isinstance(user_answer, list) else False
                else:
                    is_correct = str(user_answer).strip().upper() == str(correct_answer).strip().upper()
                
                if is_correct:
                    correct_count += 1
                    score_for_question = 1.0
                
                total_score_float += score_for_question
            
            details.append({
                'question_id': q_id,
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'is_correct': is_correct,
                'score': score_for_question,
                'type': q_type
            })
        
        # Tính điểm thang 10
        score = round((total_score_float / total_questions * 10) if total_questions > 0 else 0, 1)
        
        # Lưu kết quả vào file
        result_record = {
            'id': f"result_{user_id}_{exam_id}_{uuid.uuid4().hex[:6]}",
            'user_id': user_id,
            'username': session.get('username'),
            'grade': grade,
            'exam_id': exam_id,
            'exam_title': exam.get('title', 'Đề thi'),
            'answers': answers,
            'score': score,
            'correct_count': correct_count,
            'total_questions': total_questions,
            'details': details,
            'submitted_at': datetime.now().isoformat()
        }
        
        # Đọc file kết quả hiện tại
        results_file = 'data/exam_results.json'
        
        try:
            with open(results_file, 'r', encoding='utf-8') as f:
                all_results = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            all_results = []
        
        # Thêm kết quả mới
        all_results.append(result_record)
        
        # Lưu lại file
        ensure_directory('data')
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        
        # Xóa session thời gian làm bài
        session_key = f'exam_start_{grade}_{exam_id}'
        if session_key in session:
            session.pop(session_key)
            session.modified = True
        
        print(f"✅ Saved result: User {user_id}, Exam {exam_id}, Score {score}/10")
        
        return jsonify({
            'success': True,
            'score': score,
            'correct_count': correct_count,
            'total_questions': total_questions,
            'result_id': result_record['id'],
            'message': 'Nộp bài thành công'
        })
    
    except Exception as e:
        print(f"ERROR in nop_bai_tracnghiem: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500
##############


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt', 'zip', 'rar'}
MAX_FILE_SIZE = 10 * 1024 * 1024

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_exam_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXAM_EXTENSIONS

def ensure_directory(path):
    os.makedirs(path, exist_ok=True)

def normalize_answer_token(value):
    if value is None:
        return ''
    token = str(value).strip()
    if not token:
        return ''
    token = token.split('.')[0]
    return token.strip().upper()

def normalize_correct_answers(value):
    if isinstance(value, list):
        tokens = {normalize_answer_token(v) for v in value}
        return {t for t in tokens if t}
    token = normalize_answer_token(value)
    return {token} if token else set()

def format_correct_answer(value):
    if isinstance(value, list):
        return ', '.join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()

def calculate_tl2_score(mistakes_count):
    if mistakes_count <= 0:
        return 1.0
    if mistakes_count == 1:
        return 0.5
    if mistakes_count == 2:
        return 0.25
    if mistakes_count == 3:
        return 0.1
    return 0.0

@app.route('/forum')
@login_required
def forum():
    search_query = request.args.get('search', '').strip()
    filter_type = request.args.get('filter', 'all')
    
    if search_query:
        posts = db.search_forum_posts(search_query)
    elif filter_type == 'my_posts':
        posts = db.get_forum_posts_by_user(session['user_id'])
    else:
        posts = db.get_all_forum_posts()
    
    for post in posts:
        post['created_at_formatted'] = format_datetime(post['created_at'])
        if post.get('updated_at'):
            post['updated_at_formatted'] = format_datetime(post['updated_at'])
    
    return render_template('forum.html', 
                         posts=posts,
                         search_query=search_query,
                         filter_type=filter_type,
                         username=session.get('username'))


######################
@app.route('/forum/post/<post_id>')
@login_required
def forum_post_detail(post_id):
    post = db.get_forum_post_by_id(post_id)
    
    if not post:
        flash('Bài viết không tồn tại', 'danger')
        return redirect(url_for('forum'))
    
    db.increment_post_views(post_id)
    
    comments = db.get_comments_by_post(post_id)
    
    post['created_at_formatted'] = format_datetime(post['created_at'])
    if post.get('updated_at'):
        post['updated_at_formatted'] = format_datetime(post['updated_at'])
    
    for comment in comments:
        comment['created_at_formatted'] = format_datetime(comment['created_at'])
    
    is_author = post['author_id'] == session['user_id']
    
    return render_template('forum_post_detail.html',
                         post=post,
                         comments=comments,
                         is_author=is_author,
                         current_user_id=session['user_id'],  # ✅ THÊM DÒNG NÀY
                         username=session.get('username'))
                         ####################################################3


@app.route('/forum/create', methods=['GET', 'POST'])
@login_required
def forum_create_post():
    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            tags_str = request.form.get('tags', '').strip()
            
            if not title or not content:
                return jsonify({'success': False, 'message': 'Vui lòng nhập đầy đủ tiêu đề và nội dung'})
            
            tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()] if tags_str else []
            
            attachments = []
            if 'files' in request.files:
                files = request.files.getlist('files')
                for file in files:
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
                        
                        os.makedirs(FORUM_UPLOAD_FOLDER, exist_ok=True)
                        file_path = os.path.join(FORUM_UPLOAD_FOLDER, unique_filename)
                        file.save(file_path)
                        
                        file_size = os.path.getsize(file_path)
                        
                        file_ext = filename.rsplit('.', 1)[1].lower()
                        file_type = 'image' if file_ext in {'png', 'jpg', 'jpeg', 'gif'} else 'file'
                        
                        attachments.append({
                            'type': file_type,
                            'filename': filename,
                            'path': file_path.replace('\\', '/'),
                            'size': file_size
                        })
            
            user = get_user_by_id(session['user_id'])
            
            post_data = {
                'title': title,
                'content': content,
                'author_id': session['user_id'],
                'author_name': session.get('username', 'Unknown'),
                'author_role': user.get('role', 'student') if user else 'student',
                'attachments': attachments,
                'tags': tags
            }
            
            post_id = db.create_forum_post(post_data)
            
            return jsonify({'success': True, 'post_id': post_id, 'message': 'Tạo bài viết thành công'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    
    return render_template('forum_create_post.html', username=session.get('username'))


@app.route('/forum/edit/<post_id>', methods=['GET', 'POST'])
@login_required
def forum_edit_post(post_id):
    post = db.get_forum_post_by_id(post_id)
    
    if not post:
        flash('Bài viết không tồn tại', 'danger')
        return redirect(url_for('forum'))
    
    if post['author_id'] != session['user_id']:
        flash('Bạn không có quyền chỉnh sửa bài viết này', 'danger')
        return redirect(url_for('forum'))
    
    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            tags_str = request.form.get('tags', '').strip()
            
            if not title or not content:
                return jsonify({'success': False, 'message': 'Vui lòng nhập đầy đủ tiêu đề và nội dung'})
            
            tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()] if tags_str else []
            
            attachments = post.get('attachments', [])
            
            if 'files' in request.files:
                files = request.files.getlist('files')
                for file in files:
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
                        
                        os.makedirs(FORUM_UPLOAD_FOLDER, exist_ok=True)
                        file_path = os.path.join(FORUM_UPLOAD_FOLDER, unique_filename)
                        file.save(file_path)
                        
                        file_size = os.path.getsize(file_path)
                        file_ext = filename.rsplit('.', 1)[1].lower()
                        file_type = 'image' if file_ext in {'png', 'jpg', 'jpeg', 'gif'} else 'file'
                        
                        attachments.append({
                            'type': file_type,
                            'filename': filename,
                            'path': file_path.replace('\\', '/'),
                            'size': file_size
                        })
            
            post_data = {
                'title': title,
                'content': content,
                'attachments': attachments,
                'tags': tags
            }
            
            success = db.update_forum_post(post_id, post_data)
            
            if success:
                return jsonify({'success': True, 'message': 'Cập nhật bài viết thành công'})
            else:
                return jsonify({'success': False, 'message': 'Cập nhật thất bại'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    
    return render_template('forum_create_post.html', 
                         post=post, 
                         edit_mode=True,
                         username=session.get('username'))


@app.route('/forum/delete/<post_id>', methods=['POST'])
@login_required
def forum_delete_post(post_id):
    post = db.get_forum_post_by_id(post_id)
    
    if not post:
        return jsonify({'success': False, 'message': 'Bài viết không tồn tại'})
    
    if post['author_id'] != session['user_id']:
        return jsonify({'success': False, 'message': 'Bạn không có quyền xóa bài viết này'})
    
    for attachment in post.get('attachments', []):
        try:
            if os.path.exists(attachment['path']):
                os.remove(attachment['path'])
        except:
            pass
    
    db.delete_forum_post(post_id)
    
    return jsonify({'success': True, 'message': 'Xóa bài viết thành công'})


@app.route('/forum/comment/<post_id>', methods=['POST'])
@login_required
def forum_add_comment(post_id):
    try:
        post = db.get_forum_post_by_id(post_id)
        
        if not post:
            return jsonify({'success': False, 'message': 'Bài viết không tồn tại'})
        
        content = request.form.get('content', '').strip()
        parent_id = request.form.get('parent_id', '').strip()###########################################
        
        if not content:
            return jsonify({'success': False, 'message': 'Vui lòng nhập nội dung bình luận'})
        
        attachments = []
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
                    
                    os.makedirs(FORUM_UPLOAD_FOLDER, exist_ok=True)
                    file_path = os.path.join(FORUM_UPLOAD_FOLDER, unique_filename)
                    file.save(file_path)
                    
                    file_size = os.path.getsize(file_path)
                    file_ext = filename.rsplit('.', 1)[1].lower()
                    file_type = 'image' if file_ext in {'png', 'jpg', 'jpeg', 'gif'} else 'file'
                    
                    attachments.append({
                        'type': file_type,
                        'filename': filename,
                        'path': file_path.replace('\\', '/'),
                        'size': file_size
                    })
        
        user = get_user_by_id(session['user_id'])
        
        comment_data = {
            'post_id': post_id,
            'author_id': session['user_id'],
            'author_name': session.get('username', 'Unknown'),
            'author_role': user.get('role', 'student') if user else 'student',
            'content': content,
            'attachments': attachments,
            'parent_id': parent_id if parent_id else None ###########################################################33
        }
        
        comment_id = db.add_comment(comment_data)
        
        return jsonify({'success': True, 'comment_id': comment_id, 'message': 'Thêm bình luận thành công'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})


@app.route('/forum/delete-comment/<comment_id>', methods=['POST'])
@login_required
def forum_delete_comment(comment_id):
    comments = db._load_json(db.forum_comments_file)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    
    if not comment:
        return jsonify({'success': False, 'message': 'Bình luận không tồn tại'})
    
    if comment['author_id'] != session['user_id']:
        return jsonify({'success': False, 'message': 'Bạn không có quyền xóa bình luận này'})
    
    for attachment in comment.get('attachments', []):
        try:
            if os.path.exists(attachment['path']):
                os.remove(attachment['path'])
        except:
            pass
    
    db.delete_comment(comment_id)
    
    return jsonify({'success': True, 'message': 'Xóa bình luận thành công'})


def format_datetime(iso_string):
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.strftime('%d/%m/%Y %H:%M')
    except:
        return iso_string
#######
@app.route('/chat')
@login_required
def chat_room():
    messages = db.get_all_chat_messages()
    
    for msg in messages:
        msg['created_at_formatted'] = format_datetime(msg['created_at'])
    
    return render_template('chat_room.html',
                         messages=messages,
                         username=session.get('username'))


@app.route('/api/chat/send', methods=['POST'])
@login_required
def send_chat_message():
    try:
        data = request.get_json()
        content = data.get('content', '').strip()
        reply_to = data.get('reply_to')
        
        if not content:
            return jsonify({'success': False, 'message': 'Nội dung không được để trống'})
        
        user = get_user_by_id(session['user_id'])
        
        message_data = {
            'content': content,
            'author_id': session['user_id'],
            'author_name': session.get('username', 'Unknown'),
            'author_role': user.get('role', 'student') if user else 'student',
            'reply_to': reply_to
        }
        
        message_id = db.add_chat_message(message_data)
        message = db.get_chat_message_by_id(message_id)
        message['created_at_formatted'] = format_datetime(message['created_at'])
        
        return jsonify({
            'success': True,
            'message': message
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})


@app.route('/api/chat/messages')
@login_required
def get_chat_messages():
    try:
        last_id = request.args.get('last_id', '')
        messages = db.get_chat_messages_after(last_id)
        
        for msg in messages:
            msg['created_at_formatted'] = format_datetime(msg['created_at'])
        
        return jsonify({
            'success': True,
            'messages': messages
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})


@app.route('/api/chat/delete/<message_id>', methods=['POST'])
@login_required
def delete_chat_message(message_id):
    try:
        message = db.get_chat_message_by_id(message_id)
        
        if not message:
            return jsonify({'success': False, 'message': 'Tin nhắn không tồn tại'})
        
        if message['author_id'] != session['user_id']:
            return jsonify({'success': False, 'message': 'Bạn không có quyền xóa tin nhắn này'})
        
        db.delete_chat_message(message_id)
        
        return jsonify({'success': True, 'message': 'Đã xóa tin nhắn'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})

#################

########################
@app.route('/teacher/import_exam_ai', methods=['GET', 'POST'])
@teacher_required
def import_exam_ai():
    """
    Import đề thi tự động bằng AI
    """
    form_data = {
        'title': '',
        'description': '',
        'time_limit': '15',
        'grade': DEFAULT_GRADE
    }
    
    if request.method == 'POST':
        try:
            grade = request.form.get('grade', '').strip()
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            time_limit = request.form.get('time_limit', '15').strip()
            exam_file = request.files.get('exam_file')
            
            # Validate
            errors = []
            
            if grade not in AVAILABLE_GRADES:
                errors.append('Vui lòng chọn khối lớp hợp lệ')
            
            if not title:
                errors.append('Vui lòng nhập tên đề thi')
            
            if not exam_file or not exam_file.filename:
                errors.append('Vui lòng chọn file đề thi')
            elif not allowed_exam_file(exam_file.filename):
                errors.append('Chỉ chấp nhận file .docx')
            
            if errors:
                return jsonify({
                    'success': False,
                    'message': ' | '.join(errors)
                })
            
            # Lưu file tạm
            secure_name = secure_filename(exam_file.filename)
            ensure_directory(EXAM_UPLOAD_FOLDER)
            temp_filename = f"{uuid.uuid4().hex}_{secure_name}"
            temp_path = os.path.join(EXAM_UPLOAD_FOLDER, temp_filename)
            exam_file.save(temp_path)
            
            try:
                # Đọc nội dung Word
                docx_text = extract_text_from_docx(temp_path)
                
                if not docx_text or len(docx_text) < 50:
                    raise ValueError("File Word không có nội dung hoặc nội dung quá ngắn")
                
                # Chuyển đổi bằng AI
                exam_data = convert_exam_with_ai(docx_text, title, description)
                
                # Validate
                validation_errors = validate_exam_data(exam_data)
                if validation_errors:
                    raise ValueError("Lỗi dữ liệu: " + " | ".join(validation_errors))
                
                # Xóa file tạm
                os.remove(temp_path)
                
                return jsonify({
                    'success': True,
                    'exam_data': exam_data,
                    'message': f'AI đã tạo {len(exam_data["questions"])} câu hỏi'
                })
            
            except Exception as e:
                # Xóa file tạm nếu lỗi
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise e
        
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Lỗi: {str(e)}'
            })
    
    return render_template('import_exam_ai.html',
                         form_data=form_data,
                         grade_choices=AVAILABLE_GRADES,
                         grade_labels=GRADE_LABELS)


@app.route('/teacher/save_exam_ai', methods=['POST'])
@teacher_required
def save_exam_ai():
    """
    Lưu đề thi sau khi AI tạo
    """
    try:
        data = request.get_json()
        grade = data.get('grade', '').strip()
        exam_data = data.get('exam_data', {})
        
        if grade not in AVAILABLE_GRADES:
            return jsonify({'success': False, 'message': 'Lớp không hợp lệ'})
        
        if not exam_data or 'questions' not in exam_data:
            return jsonify({'success': False, 'message': 'Dữ liệu đề thi không hợp lệ'})
        
        # Tạo exam record
        exam_id = f"exam_{grade}_{uuid.uuid4().hex[:6]}"
        
        # Đảm bảo mỗi câu hỏi có id
        for idx, q in enumerate(exam_data['questions'], start=1):
            q['id'] = idx
            q['number'] = idx
        
        exam_record = {
            'id': exam_id,
            'title': exam_data.get('title', 'Đề thi'),
            'description': exam_data.get('description', ''),
            'time_limit': exam_data.get('time_limit', 15),
            'questions': exam_data['questions'],
            'allow_multiple_answers': False,  # Không có câu nhiều đáp án
            'created_by': session.get('user_id'),
            'created_by_name': session.get('username'),
            'created_at': datetime.now().isoformat(),
            'created_by_ai': True  # Đánh dấu tạo bởi AI
        }
        
        # Lưu vào database
        db.add_exam(grade, exam_record)
        
        return jsonify({
            'success': True,
            'exam_id': exam_id,
            'message': 'Lưu đề thi thành công'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        })
#######################
@app.route('/lop6')
@login_required
def lop6():
    return render_template('lop6.html', username=session.get('username'))


@app.route('/lop7')
@login_required
def lop7():
    return render_template('lop7.html', username=session.get('username'))


@app.route('/lop8')
@login_required
def lop8():
    return render_template('lop8.html', username=session.get('username'))


@app.route('/lop9')
@login_required
def lop9():
    return render_template('lop9.html', username=session.get('username'))
@app.route('/onthi')
@login_required
def onthi():
    return render_template('onthi.html')
################
@app.route('/xinchao')
@login_required
def xinchao():
    return render_template('menu.html', username=session.get('username'))
#########################3
if __name__ == '__main__':
    ensure_directory('data')
    ensure_directory('static/css')
    ensure_directory('static/js')
    ensure_directory('templates')
    ensure_directory(FORUM_UPLOAD_FOLDER)
    ensure_directory(EXAM_UPLOAD_FOLDER)

    port = int(os.getenv('PORT', os.getenv('FLASK_RUN_PORT', 5001)))
    debug_mode = os.getenv('FLASK_DEBUG', 'true').lower() == 'true'

    app.run(debug=debug_mode, host='0.0.0.0', port=port)
