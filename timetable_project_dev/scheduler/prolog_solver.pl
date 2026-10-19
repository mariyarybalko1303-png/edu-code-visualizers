% Підключення бібліотеки обмежень скінченних доменів (CLP(FD))
:- use_module(library(clpfd)).

% Приклад правила розкладу:
% schedule(Дні, Пари, Викладачі, Групи, Аудиторії)

solve_timetable(Teachers, Rooms, Slots, Assignment) :-
    % Assignment містить пари [День, Пара, Викладач, Група, Аудиторія]
    same_length(Slots, Assignment),
    
    % Обмеження: кожен слот має дійсні координати
    check_constraints(Assignment).

check_constraints([]).
check_constraints([Item | Rest]) :-
    safe_item(Item, Rest),
    check_constraints(Rest).

% Правила відсутності колізій (аналог логіки Prolog)
safe_item(_, []).
safe_item([Day, Period, Teacher, Group, Room], [[Day, Period, OtherTeacher, OtherGroup, OtherRoom] | Rest]) :-
    % Викладач не може бути в один час у різних місцях
    Teacher \= OtherTeacher,
    % Аудиторія не може бути зайнята різними парами
    Room \= OtherRoom,
    % Група не може мати дві пари одночасно
    Group \= OtherGroup,
    safe_item([Day, Period, Teacher, Group, Room], Rest).
safe_item(Item, [Other | Rest]) :-
    Item \= Other,
    safe_item(Item, Rest).
