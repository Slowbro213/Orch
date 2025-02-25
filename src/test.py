from flask import Flask, request, jsonify
import subprocess
import tempfile
import os
import uuid
import threading
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'), format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Configuration from environment variables
EXECUTION_TIMEOUT = int(os.getenv('EXECUTION_TIMEOUT', 10))
PYTHON_IMAGE = os.getenv('PYTHON_IMAGE', 'python:3.13-slim')
GCC_IMAGE = os.getenv('GCC_IMAGE', 'gcc')
OPENJDK_IMAGE = os.getenv('OPENJDK_IMAGE', 'openjdk')
CONTAINER_MEMORY_LIMIT = os.getenv('CONTAINER_MEMORY_LIMIT', '50m')
CONTAINER_CPU_LIMIT = float(os.getenv('CONTAINER_CPU_LIMIT', '0.5'))

# Language configurations
LANGUAGE_CONFIGS = {
    "python": {
        "image": PYTHON_IMAGE,
        "file_ext": ".py",
        "compile_cmd": None,  # Python does not need compilation
        "code_order": lambda user_code, template: user_code + '\n' + template,
        "run_cmd": lambda dir: ["python", f"{dir}/user_code.py"]
    },
    "c": {
        "image": GCC_IMAGE,
        "file_ext": ".c",
        "compile_cmd": lambda dir: ["sh", "-c", f"gcc -Ofast {dir}/user_code.c -o {dir}/user_code"],
        "code_order": lambda user_code, template: template + '\n' + user_code,
        "run_cmd": lambda dir: [f"{dir}/user_code"]
    },
    "java": {
        "image": OPENJDK_IMAGE,
        "file_ext": ".java",
        "compile_cmd": lambda dir: ["javac", "-g:none", "-O", "-J-Xms16m", "-J-Xmx32m", f"{dir}/user_code.java"],
        "code_order": lambda user_code, template: template + '\n' + user_code,
        "run_cmd": lambda dir: [
            "java",
            "-Xms32m",
            "-Xmx64m",
            "-XX:+UseSerialGC",
            "-XX:+DisableExplicitGC",
            "-Djava.security.manager",
            "-cp", dir, "Main"
        ]
        }
}

@app.route('/execute', methods=['POST'])
def execute_code():
    try:
        # Get request data
        language = request.json.get('language')
        user_code = request.json.get('user_code')
        template = request.json.get('template', '')
        tests = request.json.get('tests', {})
        
        if not user_code or language not in LANGUAGE_CONFIGS:
            return jsonify({'error': 'Invalid request', 'code': 400})
        
        config = LANGUAGE_CONFIGS[language]
        complete_code = config["code_order"](user_code, template)
        
        # Create a temporary directory for the code and binary
        temp_dir = f"/dev/shm/{uuid.uuid4()}"
        os.makedirs(temp_dir, exist_ok=True)
        code_path = os.path.join(temp_dir, f"user_code{config['file_ext']}")
        
        # Write the complete code to the temporary file
        with open(code_path, 'w') as f:
            f.write(complete_code)
        
        # Ensure the directory is writable
        os.chmod(temp_dir, 0o777)
        
        # Mount the temporary directory to the Docker container
        container_volume = f"{temp_dir}:/usr/src/app:rw"
        
        # Generate a completely random container name
        container_name = f"container_{uuid.uuid4().hex}"  # Random name (e.g., container_abc123...)
        
        # Compile the code if needed
        if config["compile_cmd"]:
            compile_cmd = [
                'docker', 'run', '--rm',
                '--cap-drop=ALL', '--security-opt=no-new-privileges', '--read-only',
                '--tmpfs', '/tmp',  # Writable /tmp for temporary files
                '-v', container_volume,
                config["image"]
            ] + config["compile_cmd"]("/usr/src/app")
            
            compile_result = subprocess.run(compile_cmd, capture_output=True, text=True)
            
            if compile_result.returncode != 0:
                return jsonify({
                    'error': 'Compilation failed',
                    'message': compile_result.stderr,
                    'code': compile_result.returncode
                })
            
            # Verify the binary/class file was created
            if language == "c" and not os.path.exists(os.path.join(temp_dir, "user_code")):
                return jsonify({'error': 'Binary not created after compilation'})
            elif language == "java" and not os.path.exists(os.path.join(temp_dir, "Main.class")):
                return jsonify({'error': 'Class file not created after compilation'})
        
        # Run tests
        for test_input, expected_output in tests.items():
            run_cmd = [
              'docker', 'run', '--name', container_name, '--rm',
              '--cap-drop=ALL', '--security-opt=no-new-privileges', '--read-only',
              '--tmpfs', '/dev/shm',  # Writable /dev/shm for temporary files
              '-v', f'{temp_dir}:/usr/src/app:ro',  # Mount /usr/src/app as read-only
              '--network', 'none',  # Disable internet access
              '-i',
              config["image"]
]           + config["run_cmd"]("/usr/src/app")
            
            try:
                result = subprocess.run(run_cmd, capture_output=True, text=True, input=test_input, timeout=EXECUTION_TIMEOUT)
            except subprocess.TimeoutExpired:
                print("Timeout")
                def stop_container():

                    try:
                        subprocess.run(
                            ['docker', 'stop', container_name],
                        )
                    except Exception as e:
                        logging.error(f"Error stopping container: {e}")
                
                threading.Thread(target=stop_container, daemon=True).start()
                return jsonify({
                    'error': 'Execution timed out',
                    'message': f'The code took too long to execute (>{EXECUTION_TIMEOUT} seconds).',
                    'hint': 'Optimize your code or reduce its complexity.',
                    'code': 408
                }), 408
            
            if result.returncode != 0:
                return jsonify({
                    'input': test_input,
                    'error': 'Runtime error',
                    'message': result.stderr,
                    'hint': 'Check your code for errors or unintended behavior.',
                    'code': result.returncode
                })
            
            if result.stdout.strip() != expected_output:
                return jsonify({
                    'input': test_input,
                    'expected': expected_output,
                    'actual': result.stdout.strip(),
                    'error': 'Output mismatch',
                    'hint': 'Ensure your code produces the correct output.',
                    'code': 600
                })
        
        # Clean up the temporary directory
        if os.path.exists(temp_dir):
            subprocess.run(['rm', '-rf', temp_dir])
        
        return jsonify({'message': "Success!", 'code': 0})
    
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({'error': str(e), 'code': 500})

if __name__ == '__main__':
    app.run(host=os.getenv('HOST', '0.0.0.0'), port=int(os.getenv('PORT', 5000)))
