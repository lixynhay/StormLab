#!/usr/bin/env python3
"""
Скрипт для создания полного дампа кода проекта в один .txt файл.
Игнорирует .venv, __pycache__, .git и другие служебные папки.
"""

import os
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent
OUTPUT_FILE = PROJECT_ROOT / f"project_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

# Папки для игнорирования
IGNORE_DIRS = {
    '.venv', '__pycache__', '.git', '.idea', '.vscode',
    'data', 'node_modules', 'venv', 'env'
}

# Расширения файлов для включения
INCLUDE_EXTENSIONS = {'.py', '.env', '.txt', '.md'}


def should_ignore(path: Path) -> bool:
    """Проверяет, нужно ли игнорировать путь."""
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
    return False


def create_dump():
    """Создает дамп всего кода проекта."""
    print(f"📁 Проект: {PROJECT_ROOT}")
    print(f" Вывод: {OUTPUT_FILE}")
    print()
    
    files_found = []
    
    # Собираем все файлы
    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)
        
        # Пропускаем игнорируемые директории
        if should_ignore(root_path):
            dirs.clear()
            continue
        
        # Фильтруем файлы
        for file in files:
            file_path = root_path / file
            if file_path.suffix in INCLUDE_EXTENSIONS:
                files_found.append(file_path)
    
    print(f"📊 Найдено файлов: {len(files_found)}")
    print()
    
    # Записываем дамп
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
        outfile.write("=" * 80 + "\n")
        outfile.write("STORMLAB PROJECT DUMP\n")
        outfile.write(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        outfile.write("=" * 80 + "\n\n")
        
        for file_path in sorted(files_found):
            relative_path = file_path.relative_to(PROJECT_ROOT)
            print(f"  📄 {relative_path}")
            
            outfile.write("=" * 80 + "\n")
            outfile.write(f"FILE: {relative_path}\n")
            outfile.write("=" * 80 + "\n")
            
            try:
                with open(file_path, 'r', encoding='utf-8') as infile:
                    content = infile.read()
                    outfile.write(content)
                    if not content.endswith('\n'):
                        outfile.write('\n')
            except Exception as e:
                outfile.write(f"⚠️ Ошибка чтения файла: {e}\n")
            
            outfile.write("\n")
    
    print()
    print(f"✅ Дамп создан: {OUTPUT_FILE.name}")
    print(f"📊 Размер: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")
    print()
    print("💡 Теперь можешь скопировать содержимое и вставить в чат!")


if __name__ == "__main__":
    create_dump()