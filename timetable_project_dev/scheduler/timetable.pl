:- use_module(library(clpfd)).

% Формат завдання у Prolog:
% task(TaskID, TeacherID, RoomID, IsStream, DayVar, PeriodVar, GroupsList)
solve_timetable([], _).
solve_timetable(Tasks, AllVars) :-
    extract_days_periods(Tasks, Days, Periods),
    
    % Домени: Дні (1..5 — понеділок-п'ятниця), Пари (1..7)
    Days ins 1..5,
    Periods ins 1..7,
    
    % Перевірка всіх обмежень та колізій
    check_all_constraints(Tasks),
    
    % Пошук рішення через labeling з евристикою ff (first fail)
    append(Days, Periods, AllVars),
    labeling([ff, asc], AllVars).

extract_days_periods([], [], []).
extract_days_periods([task(_, _, _, _, D, P, _) | Rest], [D | Days], [P | Periods]) :-
    extract_days_periods(Rest, Days, Periods).

check_all_constraints([]).
check_all_constraints([Task | Rest]) :-
    no_collisions_with_rest(Task, Rest),
    check_all_constraints(Rest).

no_collisions_with_rest(_, []).
no_collisions_with_rest(task(ID1, T1, R1, Stream1, D1, P1, G1), [task(ID2, T2, R2, Stream2, D2, P2, G2) | Rest]) :-
    ID1 \= ID2,
    % Якщо день і пара збігаються, перевіряємо ресурси
    (   (D1 #= D2, P1 #= P2) #=> 
        (
          % 1. Викладач не може бути в двох місцях одночасно
          T1 #\= T2,
          
          % 2. Аудиторія не може бути зайнята різними парами
          R1 #\= R2,
          
          % 3. Перевірка груп та потоків
          groups_compatible(Stream1, G1, Stream2, G2)
        )
    ),
    no_collisions_with_rest(task(ID1, T1, R1, Stream1, D1, P1, G1), Rest).

% Правила сумісності груп:
% Якщо обидва заняття є тотожним потоком (однакові групи), вони можуть йти разом.
% В іншому випадку групи не повинні перетинатися в один і той же час.
groups_compatible(1, G1, 1, G2) :-
    G1 == G2.  % Однаковий спільний потік — дозволено
groups_compatible(_, G1, _, G2) :-
    intersection_empty(G1, G2). % Жодної спільної групи у непотокових заняттях

intersection_empty([], _).
intersection_empty([H | T], L2) :-
    \+ member(H, L2),
    intersection_empty(T, L2).
