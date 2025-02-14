#!/bin/bash

# Create request payload
cat > request.json <<EOF
{
    "text": "def shuma(arr):\n  for x in range(10000000):\n    a=5\n  return sum(arr)",
    "language": "python",
    "template": "import sys\nimport json\nn = int(input())\narr = list(map(int, input().split()))\nprint(shuma(arr))",
    "tests": {
        "3\\n1 2 3": "6",
        "5\\n1 2 3 4 5": "15"
    }
}
EOF

# Get start time in seconds with decimal
start_time=$(date +%s.%N)

# Send 20 concurrent requests
seq 20 | xargs -P 20 -I {} curl -s -X POST \
    -H "Content-Type: application/json" \
    -d @request.json \
    http://localhost/execute > /dev/null

# Get end time
end_time=$(date +%s.%N)

# Calculate duration using awk
duration=$(awk -v start="$start_time" -v end="$end_time" 'BEGIN {print end - start}')
echo "Total execution time: ${duration} seconds"
