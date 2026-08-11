# <CODE> — <assignment title>

Write your code in `main.cpp`. Full instructions are on Canvas.

## Compile (read any errors it prints)
```
g++ -std=c++17 -Wall -Wextra main.cpp -o main
```

## Run
```
./main < data/data1.txt
```

## Test (the same checks the autograder runs)
```
data/run.sh
pytest -rP -m T1
```
`data/run.sh` produces `result1.txt`, `result2.txt`, … and the tests read those files.

Submit by committing and pushing; the green check on GitHub means the autograder passed.
