:- use_module(library(clpfd)).

% Головний предикат: розв'язання задачі розкладу
% Task формати: task(ID, TeacherID, GroupID, RoomID, Day, Period)
solve_timetable(Tasks) :-
    extract_vars(Tasks, Days, Periods),
    
    % Домени днів (1..5 — понеділок-п'ятниця) та пар (1..7)
    Days ins 1..5,
    Periods ins 1..7,
    
    % Застосування обмежень (немає колізій)
    all_valid_constraints(Tasks),
    
    % Пошук рішення (labeling)
    append(Days, Periods, Vars),
    labeling([ff], Vars).

extract_vars([], [], []).
extract_vars([task(_, _, _, _, D, P) | Rest], [D | Days], [P | Periods]) :-
    extract_vars(Rest, Days, Periods).

% Перевірка відсутності колізій між усіма парами завдань
all_valid_constraints([]).
all_valid_constraints([Task | Rest]) :-
    check_no_collisions(Task, Rest),
    all_valid_constraints(Rest).

check_no_collisions(_, []).
check_no_collisions(task(ID1, T1, G1, R1, D1, P1), [task(ID2, T2, G2, R2, D2, P2) | Rest]) :-
    ID1 \= ID2,
    % Якщо день і пара однакові — ресурси не повинні перетинатися
    (   (D1 #= D2, P1 #= P2) #=> 
        (
          T1 #\= T2,  % Один викладач не може вести дві пари одночасно
          R1 #\= R2,  % Одна аудиторія не може бути зайнята різними парами
          G1 #\= G2   % Група не може мати дві пари одночасно
        )
    ),
    check_no_collisions(task(ID1, T1, G1, R1, D1, P1), Rest).
