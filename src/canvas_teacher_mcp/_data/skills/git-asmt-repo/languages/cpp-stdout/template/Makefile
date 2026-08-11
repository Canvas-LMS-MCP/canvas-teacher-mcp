# L2 cpp-stdout TEMPLATE — the graded unit is the program's OUTPUT, so there is no tests.cpp.
all: clean run
main: main.cpp
	g++ -Wall -Wextra --std=c++17 main.cpp -o main
run: main
	chmod +x data/run.sh && data/run.sh
clean:
	rm -rf main a.out *.o *.dSYM __pycache__ .pytest_cache
	rm -f result*.txt
