;; dump_upstream.il — 只读 dump 上游 OPA_D 每个实例的 master 与参数存法
;; 目的：确定“写尺寸”的正确方式（master view / 属性名 / 是否 pcell）
(printf "\n=== DUMP START\n")

(procedure (dumpCv libName cellName viewName)
  (let (cv)
    (setq cv (dbOpenCellViewByType libName cellName viewName "schematic" "r"))
    (if (null cv)
        (printf "ERROR: 打不开 %s/%s/%s\n" libName cellName viewName)
        (progn
          (printf "\n--- %s/%s/%s : %d instances\n"
                  libName cellName viewName (length cv~>instances))
          (foreach inst cv~>instances
            (let (m)
              (setq m inst~>master)
              (printf "INST %-8s master=%s/%s/%s isParamCell=%L\n"
                      inst~>name m~>libName m~>cellName m~>viewName m~>isParamCell)
              (foreach pn (list "w" "l" "nf" "fingers" "m" "fw" "simW" "r" "segW" "segL" "c")
                (let (v)
                  (setq v (errset (dbGet inst pn) t))
                  (when (and v (car v))
                    (printf "    %-8s = %L\n" pn (car v))))))))))))

(dumpCv "weekfour_last" "OPA_D" "schematic")

;; 顺便看有没有别的相关 cell（测试台/符号）
(foreach cell '("OPA_D")
  (let (c)
    (setq c (ddGetObj "weekfour_last" cell))
    (when c
      (printf "\ncell %s views: %L\n" cell (mapcar 'car (mapcar 'list c~>views))))))

(printf "\n=== DUMP DONE\n")
(exit)