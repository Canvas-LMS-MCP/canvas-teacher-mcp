#!/bin/sh
# Build once, then run the program on EVERY data set, capturing each run's stdout.
# resultN.txt <- data/dataN.txt.  More than one data set is required (L1 §3): a single input
# lets a student hard-code the answer and still pass.
g++ -Wall -Wextra --std=c++17 main.cpp -o main || exit 1
for f in data/data*.txt; do
  n=$(basename "$f" .txt | sed 's/^data//')
  timeout 10 ./main < "$f" > "result$n.txt"
done
